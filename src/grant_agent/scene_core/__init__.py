"""Shared transcribe -> define -> judge -> improve mechanism (Scene v1).

Adapters provide observation and reversible domain actions, never a second judge.
Source text, vocabulary and episode feedback carry no execution authority.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Callable

SCHEMA = 'neyvia.scene.v1'
_ADAPTERS = {}


@dataclass
class Adapter:
    transcribe: Callable
    vocabulary: Callable
    fixes: dict = field(default_factory=dict)
    checkpoint: Callable | None = None
    restore: Callable | None = None
    episode_input: Callable | None = None


def register(domain: str, adapter: Adapter):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', domain) or not isinstance(adapter, Adapter):
        raise ValueError('Expected a domain id and an Adapter')
    if domain in _ADAPTERS and _ADAPTERS[domain] is not adapter:
        raise ValueError('Domain already registered: ' + domain)
    _ADAPTERS[domain] = adapter


def adapter(domain):
    if domain not in _ADAPTERS and domain == 'ui':
        from ..laya_glance import ui_adapter
        register(domain, ui_adapter())
    if domain not in _ADAPTERS and domain == 'laya3d':
        from .image_model import make_adapter
        register(domain, make_adapter())
    if domain not in _ADAPTERS and domain in {'blender','godot','unity','roblox'}:
        from .gamedev import make_adapter
        register(domain, make_adapter(domain))
    if domain not in _ADAPTERS and domain == 'video':
        from ..laya_video import make_adapter as video_adapter
        register(domain, video_adapter())
    if domain not in _ADAPTERS and domain == 'video-edit':
        from ..laya_video_edit import edit_adapter
        register(domain, edit_adapter())
    if domain not in _ADAPTERS:
        raise ValueError('No domain adapter registered: ' + domain)
    return _ADAPTERS[domain]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def transcribe(domain, source):
    started = time.perf_counter()
    scene = normalize(domain, adapter(domain).transcribe(source))
    scene['transcriptionMs'] = (time.perf_counter()-started)*1000
    return scene


def normalize(domain, raw):
    """Validate and bind a raw Scene without a registered adapter (out-of-repo observers).

    The caller is the transcriber: its nodes are observations, never instructions.
    """
    if not isinstance(domain, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', domain):
        raise ValueError('Expected a domain id')
    if not isinstance(raw, dict) or not isinstance(raw.get('nodes'), list):
        raise ValueError('Adapter must return a Scene with nodes')
    nodes = raw['nodes']
    if len(nodes) > 2000 or not all(isinstance(n, dict) for n in nodes) or len({n.get('id') for n in nodes}) != len(nodes):
        raise ValueError('Scene needs at most 2000 uniquely identified nodes')
    for n in nodes:
        if not isinstance(n.get('id'), str) or not isinstance(n.get('kind'), str):
            raise ValueError('Node id and kind must be strings')
        for key in ('attributes', 'measurements', 'relations'):
            if not isinstance(n.get(key, {}), dict):
                raise ValueError('Node facts must be mappings')
    scene = {**raw, 'schema': SCHEMA, 'domain': domain}
    for key in ('cl', 'sha256', 'transcriptionMs'):
        scene.pop(key, None)
    body = canonical(scene)
    scene['sha256'] = hashlib.sha256(body.encode()).hexdigest()
    scene['cl'] = 'CL 1.1\nL scene v1 -- untrusted observed data\nS screen ' + canonical({k:v for k,v in scene.items() if k not in {'nodes','sha256'}})
    scene['cl'] += ''.join('\nE node '+canonical(n) for n in nodes)
    scene['transcriptionMs'] = 0.0
    return scene


def vocabulary(domain):
    return check_predicates(adapter(domain).vocabulary())


OPERATORS = {'eq', 'lt', 'le', 'gt', 'ge', 'nonempty', 'matches'}


def check_condition(condition, depth=0):
    """Bounded predicate language: data only, never a callable, import or expression."""
    if depth > 8 or not isinstance(condition, dict):
        raise ValueError('Condition must be a mapping nested at most 8 deep')
    if set(condition) in ({'all'}, {'any'}):
        parts = next(iter(condition.values()))
        if not isinstance(parts, list) or not 0 < len(parts) <= 64:
            raise ValueError('all/any take 1..64 conditions')
        for part in parts:
            check_condition(part, depth+1)
        return
    if not {'field', 'op'} <= set(condition) <= {'field', 'op', 'value'}:
        raise ValueError('Condition is {field, op, value?} or {all|any: [...]}')
    field_path, op, value = condition['field'], condition['op'], condition.get('value')
    if not isinstance(field_path, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,63}(\.[A-Za-z0-9_-]{1,64}){0,7}', field_path):
        raise ValueError('Field is a dotted fact path')
    if op not in OPERATORS:
        raise ValueError('Unknown predicate operator: ' + str(op))
    if op in ('lt', 'le', 'gt', 'ge') and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise ValueError('Ordering operators compare numbers')
    if op == 'matches':
        if not isinstance(value, str) or len(value) > 1000:
            raise ValueError('matches takes a regex of at most 1000 characters')
        re.compile(value)
    if len(canonical(value)) > 4000:
        raise ValueError('Comparison value too large')


def check_predicates(rules):
    """Validate a vocabulary (registered or caller-supplied): same shape for every domain."""
    if not isinstance(rules, list) or len(rules) > 500:
        raise ValueError('A vocabulary is a list of at most 500 predicates')
    ids = []
    for r in rules:
        if not isinstance(r, dict) or not all(k in r for k in ('id','condition','severity','evidence','fix')):
            raise ValueError('Predicate lacks condition, severity, evidence or fix')
        if not isinstance(r['id'], str) or not 0 < len(r['id']) <= 128:
            raise ValueError('Predicate id must be a short string')
        if not isinstance(r['severity'], str) or not isinstance(r['evidence'], list) or not all(isinstance(e, str) for e in r['evidence']):
            raise ValueError('Predicate severity is text and evidence is a list of fact paths')
        if not isinstance(r['fix'], dict) or not isinstance(r['fix'].get('action'), str):
            raise ValueError('Predicate fix names an action')
        alternatives = r['fix'].get('alternatives', [])
        if not isinstance(alternatives, list) or len(alternatives) > 8 or not all(isinstance(x, str) for x in alternatives):
            raise ValueError('Fix alternatives are at most 8 action names')
        check_condition(r['condition'])
        ids.append(r['id'])
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate predicate identity')
    return rules


_MISSING = object()


def value_at(node, path):
    value = node
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def evaluate(condition, node):
    """Three-valued bounded predicate language. Never eval/exec source."""
    if 'all' in condition or 'any' in condition:
        key = 'all' if 'all' in condition else 'any'
        vals = [evaluate(c, node) for c in condition[key]]
        if key == 'all':
            return False if False in vals else None if None in vals else True
        return True if True in vals else None if None in vals else False
    value = value_at(node, condition['field'])
    if value is _MISSING or value is None:
        return None
    op, target = condition['op'], condition.get('value')
    if op == 'eq':
        return value == target
    if op in ('lt','le','gt','ge'):
        if not isinstance(value,(int,float)) or isinstance(value,bool):
            return None
        return {'lt':lambda:value<target,'le':lambda:value<=target,'gt':lambda:value>target,'ge':lambda:value>=target}[op]()
    if op == 'nonempty':
        return bool(value)
    if op == 'matches':
        if len(str(target)) > 1000 or len(str(value)) > 16000:
            return None
        return bool(re.search(target, str(value), re.I))
    raise ValueError('Unknown predicate operator: ' + op)


def episode_input(scene):
    try:
        custom = adapter(scene['domain']).episode_input
    except ValueError:  # out-of-repo domain judged with caller-supplied predicates
        custom = None
    if custom:
        selected = custom(scene)
        if selected is not None:
            return selected
    return 'scene:'+scene['domain'], {'nodes':[{k:n.get(k,{}) for k in ('kind','attributes','measurements')} for n in scene['nodes']]}


def episode(root, scene, label, reason, source, *, user='', layer='corrective', weight=1, split=None):
    """One idempotent append. Explicit correction may use weight=1; self-observation may not."""
    from ..laya_instant import store
    if not reason or not source:
        raise ValueError('Reason and provenance are required')
    # Exclude ids, URL, root paths and labels from the frozen input representation.
    domain, data = episode_input(scene)
    return store(str(root)).learn(domain, data, label, source, user=user, layer=layer,
                                 weight=weight, split=split, evidence={'reason':reason,'sceneSha256':scene['sha256']})


def admit_approximate(findings, rules, calibration, level=0.95):
    """Admission for scenes whose facts are approximate measurements (pixels, vision).

    calibration: {predicate: {precisionLower, npvLower, tp, fp, tn, fn}} built from
    labelled episodes (conservative k/(n+1) rates). A broken verdict is admitted
    when a fired predicate's precision bound reaches ``level``; a clean verdict
    only when every crisp predicate's negative-predictive bound reaches it.
    Otherwise one model look is requested (never a tour).
    """
    calibration = calibration or {}
    crisp = [r['id'] for r in rules if not r.get('fuzzy')]
    fired = sorted({f['predicate'] for f in findings})
    trusted = [p for p in fired if calibration.get(p, {}).get('precisionLower', 0) >= level]
    weak_negatives = [p for p in crisp if calibration.get(p, {}).get('npvLower', 0) < level]
    if fired:
        admitted = bool(trusted)
        confidence = max((calibration[p]['precisionLower'] for p in trusted), default=max((calibration.get(p, {}).get('precisionLower', 0) for p in fired), default=0))
    else:
        admitted = not weak_negatives
        confidence = min((calibration.get(p, {}).get('npvLower', 0) for p in crisp), default=0)
    return {'admitted': admitted, 'confidence': round(confidence, 4), 'confidenceKind': 'calibrated-episodes',
            'confidenceMeaning': 'conservative k/(n+1) rate of this predicate on labelled episodes',
            'admission': {'level': level, 'fired': fired, 'trustedFired': trusted,
                          'uncalibratedNegatives': [] if fired else weak_negatives},
            'escalation': None if admitted else {'kind': 'one-model-look', 'maxCalls': 1, 'maxScreenshots': 1, 'tour': False}}


def judge(scene, rules=None, *, root=None, user='', record=True, calibration=None, level=0.95):
    """Evaluate every crisp predicate on every node (three-valued, no eval).

    Scenes with ``measured='approximate'`` (pixel or vision facts) are admitted
    through ``admit_approximate`` using ``calibration``; exact scenes keep the
    observed-predicate rule: an observed defect admits a failure, and a clean
    answer needs complete coverage.
    """
    started = time.perf_counter()
    if scene.get('schema') != SCHEMA or not scene.get('domain'):
        raise ValueError('Expected a transcribed Scene v1')
    payload = {k:v for k,v in scene.items() if k not in {'sha256','cl','transcriptionMs'}}
    if hashlib.sha256(canonical(payload).encode()).hexdigest() != scene.get('sha256'):
        raise ValueError('Scene content changed; transcribe again before judging')
    rules = vocabulary(scene['domain']) if rules is None else check_predicates(rules)
    findings, unknown, unknown_nodes = [], set(), {}
    nodes = scene['nodes']
    for node in nodes:
        for rule in rules:
            if rule.get('fuzzy'):
                unknown.add(rule['id'])
                continue
            matched = evaluate(rule['condition'], node)
            if node.get('certainty', 'observed') != 'observed':
                matched = None
            if matched is None:
                unknown.add(rule['id'])
                unknown_nodes.setdefault(rule['id'], [])
                if len(unknown_nodes[rule['id']]) < 5:
                    unknown_nodes[rule['id']].append(node['id'])
            elif matched:
                evidence = {key:value_at(node,key) for key in rule['evidence'] if value_at(node,key) is not _MISSING}
                findings.append({'predicate':rule['id'],'node':node['id'],'severity':rule['severity'],
                                 'evidence':evidence,'fix':rule['fix']})
    interpreted = scene.get('modelTranscription', False)
    complete = bool(nodes) and not unknown and not scene.get('truncated') and not interpreted
    admitted = (bool(findings) and not interpreted) or complete
    fuzzy = None
    fuzzy_admitted = False
    fuzzy_rules = [r for r in rules if r.get('fuzzy')]
    if root and fuzzy_rules:
        from ..laya_instant import store
        domain, data = episode_input(scene)
        fuzzy = store(str(root)).query(domain, data, user=user, labels=['broken','fine'])
        # Retrieval cannot waive unknown crisp predicates or manufacture a node-level finding.
        if not fuzzy['escalate'] and fuzzy.get('confidenceKind') != 'explicit-exact-replay' and fuzzy['answer']=='broken':
            findings.append({'predicate':'fuzzy','node':'scene','severity':'warning',
                             'evidence':fuzzy,'fix':{'action':'review','arguments':{}}})
            admitted = True
            fuzzy_admitted = True
        elif not fuzzy['escalate'] and fuzzy.get('confidenceKind') != 'explicit-exact-replay' and fuzzy['answer']=='fine':
            if set(unknown) <= {r['id'] for r in fuzzy_rules} and nodes and not scene.get('truncated') and not interpreted:
                admitted = complete = fuzzy_admitted = True
    result = {'surface':scene.get('surface',scene['domain']),'findings':findings,'admitted':bool(admitted),
              'confidence':.95 if fuzzy_admitted else 1.0 if admitted else 0.0,
              'confidenceMeaning':'nominal-conformal-level' if fuzzy_admitted else 'predicate-satisfaction-not-global-visual-accuracy',
              'confidenceKind':'cross-conformal' if fuzzy_admitted else 'observed-predicate' if admitted and not interpreted else 'uncalibrated',
              'complete':complete,'unknown':sorted(unknown),'unknownNodes':unknown_nodes,'sceneSha256':scene['sha256'],
              'vocabularySha256':hashlib.sha256(canonical(rules).encode()).hexdigest(),
              'escalation':None if admitted else {'kind':'observer-or-human' if interpreted else 'one-model-look','maxCalls':0 if interpreted else 1,'maxScreenshots':1,'tour':False}}
    if scene.get('measured') == 'approximate':
        result.update(admit_approximate(findings, rules, calibration, level))
    if root and record and result['admitted'] and scene.get('measured') != 'approximate':
        result['episode'] = episode(root, scene, 'broken' if findings else 'fine', 'Observed predicate outcome',
                                    'judge:'+scene['sha256']+':'+result['vocabularySha256'], weight=.25,
                                    split='holdout' if fuzzy_admitted else None)
    result['ms'] = (time.perf_counter()-started)*1000
    return result


def improve(domain, source, budget, *, root):
    """Apply only caller-authorized reversible fixes. Trading remains proposal-only.

    budget={max_steps:1,max_seconds:10,allowed_fixes:[...],guards:{metric:'min'|'max'},nodes?:[node id]}
    The adapter's restore must raise if rollback fails. Receipts persist each transition.
    """
    a = adapter(domain)
    if any(v not in {'min','max'} for v in budget.get('guards',{}).values()):
        raise ValueError('Metric guards use min or max')
    limit = int(budget.get('max_steps',0))
    seconds = float(budget.get('max_seconds',0))
    if not 0 <= limit <= 20 or not 0 < seconds <= 300:
        raise ValueError('Budget requires max_steps 0..20 and max_seconds in (0,300]')
    started = time.perf_counter()
    scene = transcribe(domain,source)
    verdict = judge(scene,root=root)
    receipts = []
    directory = Path(root)/'.neyvia/laya/improve'
    directory.mkdir(parents=True,exist_ok=True)
    receipt_path = directory/(str(time.time_ns())+'.json')
    def save():
        receipt_path.write_text(json.dumps({'domain':domain,'steps':receipts,'verdict':verdict},indent=2),encoding='utf-8')
    save()
    if domain == 'trading':
        return {'status':'human-review-only','proposals':verdict['findings'],'receipt':str(receipt_path),'verdict':verdict}
    for _ in range(limit):
        if time.perf_counter()-started >= seconds or not verdict['admitted']:
            break
        # A predicate names its preferred fix and may list alternative fix patterns; the
        # first one the caller allowed and the adapter registered is applied.
        # Optional caller focus: only findings on these nodes are eligible (the rest still count).
        allowed, focus = budget.get('allowed_fixes',[]), set(budget.get('nodes') or [])
        chosen = next(({**f,'fix':{**f['fix'],'action':action}} for f in verdict['findings'] if not focus or f['node'] in focus
                       for action in [f['fix']['action'],*f['fix'].get('alternatives',[])]
                       if action in allowed and action in a.fixes),None)
        if not chosen:
            break
        if a.checkpoint is None or a.restore is None:
            raise ValueError('Automatic fixes require checkpoint and restore')
        checkpoint = a.checkpoint(source)
        step = {'before':scene['sha256'],'finding':chosen,'status':'applying'}
        receipts.append(step)
        save()
        try:
            applied = a.fixes[chosen['fix']['action']](source,chosen)
            if isinstance(applied, dict):  # the adapter's own receipt of the edit
                try:
                    step['fix'] = json.loads(canonical(applied))
                except (TypeError, ValueError):
                    step['fix'] = {'unserializable': type(applied).__name__}
            after = transcribe(domain,source)
            next_verdict = judge(after,root=root)
            old={(f['predicate'],f['node']) for f in verdict['findings']}
            new={(f['predicate'],f['node']) for f in next_verdict['findings']}
            guards = budget.get('guards',{})
            metrics_before,metrics_after=scene.get('metrics',{}),after.get('metrics',{})
            guarded = all(key in metrics_before and key in metrics_after and
                          (metrics_after[key]>=metrics_before[key] if direction=='min' else metrics_after[key]<=metrics_before[key])
                          for key,direction in guards.items())
            keep = next_verdict['admitted'] and new < old and set(next_verdict['unknown']) <= set(verdict['unknown']) and guarded and time.perf_counter()-started<=seconds
            step.update(after=after['sha256'],guarded=guarded,status='kept' if keep else 'reverted')
            if keep:
                scene,verdict=after,next_verdict
            else:
                a.restore(source,checkpoint)
                if transcribe(domain,source)['sha256'] != scene['sha256']:
                    raise RuntimeError('Rollback did not restore the observed scene')
            episode(root,after,'kept' if keep else 'reverted','Fix outcome with guarded metrics','improve:'+str(receipt_path)+':'+str(len(receipts)),weight=.25)
        except Exception as exc:
            step.update(status='failed',error=type(exc).__name__+': '+str(exc))
            a.restore(source,checkpoint)
            save()
            raise
        save()
        if step['status']!='kept':
            break
    return {'status':'completed','verdict':verdict,'steps':receipts,'receipt':str(receipt_path)}


class SceneClient:
    """Typed facade over the existing SDK native-tool transport."""
    def __init__(self, call_native):
        self.call_native = call_native

    def transcribe(self, domain, source):
        return self.call_native('neyvia.scene.transcribe', {'domain':domain,'source':source})

    def vocabulary(self, domain):
        return self.call_native('neyvia.scene.vocabulary', {'domain':domain})

    def judge(self, scene, *, predicates=None, domain=None, user='', record=True):
        """Judge a Scene. With ``predicates`` an out-of-repo caller supplies its own vocabulary
        (same predicate shape, validated as data, never executed); a raw scene needs ``domain``."""
        args = {'scene':scene,'user':user,'record':record}
        if predicates is not None:
            args['predicates'] = predicates
        if domain:
            args['domain'] = domain
        return self.call_native('neyvia.laya.judge', args)

    def improve(self, domain, source, budget):
        return self.call_native('neyvia.scene.improve', {'domain':domain,'source':source,'budget':budget})

    def glance(self, *, scene=None, screenshot=None, fuzzy=False):
        """UI glance: a perception scene, a screenshot, or both (hybrid)."""
        args = {k: v for k, v in (('scene', scene), ('screenshot', screenshot)) if v is not None}
        return self.call_native('neyvia.laya.glance', {**args, 'fuzzy': fuzzy})

    def lesson(self, scene, node, predicate, label, reason, source):
        """Instant node correction for the UI vocabulary (text-intrinsic predicates)."""
        return self.call_native('neyvia.laya.glance_lesson', {'scene': scene, 'node': node, 'predicate': predicate,
                                'label': label, 'reason': reason, 'source': source})

    def episode(self, scene, label, reason, source, *, user='', layer='corrective'):
        return self.call_native('neyvia.scene.episode', {'scene':scene,'label':label,'reason':reason,
                                'source':source,'user':user,'layer':layer})


class OperationAdapter:
    """Native mutation verifier: observe persisted episodes or an improvement receipt."""
    def __init__(self, root, tool, arguments):
        self.root,self.tool,self.arguments=Path(root),tool,arguments
        self.seen=set((self.root/'.neyvia/laya/improve').glob('*.json'))

    def before(self):
        return {'receiptCount':len(self.seen)}

    def after(self):
        if self.tool=='neyvia.scene.improve':
            files=set((self.root/'.neyvia/laya/improve').glob('*.json'))-self.seen
            if len(files)!=1:return {'matched':False}
            path=files.pop()
            receipt=json.loads(path.read_text(encoding='utf-8'))
            current=transcribe(self.arguments['domain'],self.arguments['source'])
            return {'matched':receipt['domain']==self.arguments['domain'] and
                    receipt['verdict']['sceneSha256']==current['sha256'],
                    'receipt':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        from ..laya_instant import store,latest_episodes,input_key
        local=store(str(self.root));local.refresh()
        if self.tool=='neyvia.laya.glance_lesson':
            from ..laya_glance import transcribe as ui_scene,node_domain,node_key
            scene=ui_scene(self.arguments['scene'])
            node=next((n for n in scene['nodes'] if n['id']==self.arguments['node']),None)
            rows=[r for r in latest_episodes(local.rows) if r['domain']==node_domain(self.arguments['predicate'])
                  and r['source']==self.arguments['source']]
            matched=bool(rows) and node is not None and rows[-1]['label']==self.arguments['label'] and rows[-1]['key']==input_key(node_key(node,self.arguments['predicate']))
            return {'matched':matched,'episodeId':rows[-1]['id'] if rows else None,'version':local.version}
        expected_domain='ui-glance' if self.tool=='neyvia.laya.glance_learn' else episode_input(self.arguments['scene'])[0]
        rows=[r for r in latest_episodes(local.rows) if r['domain']==expected_domain and r['source']==self.arguments['source']
              and r['user']==self.arguments.get('user','') and r['layer']==self.arguments.get('layer','corrective')]
        from ..laya_instant import input_key
        if self.tool=='neyvia.laya.glance_learn':
            expected_input={'image':str((self.root/self.arguments['screenshot']).resolve())}
        else:
            expected_input=episode_input(self.arguments['scene'])[1]
        matched=bool(rows) and rows[-1]['label']==self.arguments['label'] and rows[-1]['key']==input_key(expected_input)
        return {'matched':matched,'episodeId':rows[-1]['id'] if rows else None,'version':local.version}

    def verify(self, context):
        observed=context.get('after') or {}
        return {'verified':bool(observed.get('matched')),'observed':observed}
