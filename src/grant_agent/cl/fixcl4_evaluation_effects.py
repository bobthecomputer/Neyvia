"""Fresh witnesses for bounded questions, frozen curricula and measured lab work.

Reported answers/trials retain their provenance. These observers verify the
declared mechanism and actual input bytes, never infer general model quality.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

from .record_effects import _path, _files, _sources, _json, _receipt_check, _measurement
from .effects import _measure_file

SUPPORTED = {'intelligence.ask_self', 'intelligence.answer_self', 'intelligence.brief',
             'intelligence.rationale', 'intelligence.obligate', 'intelligence.handoff',
             'lab.uncertainty', 'lab.resolve_uncertainty', 'lab.causal', 'lab.journey',
             'lab.curriculum', 'lab.visual_guard', 'lab.rehearse'}


def _protocol(protocol, name):
    if name.startswith('intelligence.'):
        return SimpleNamespace(gateway=SimpleNamespace(root=getattr(protocol.gateway, 'work_root', protocol.gateway.root)))
    return protocol


def _store(protocol, args):
    from ..workspace_intelligence import WorkspaceIntelligence
    return WorkspaceIntelligence(protocol.gateway.root, args['workId'])


def _lab(protocol):
    from ..improvement_lab import ImprovementLab
    return ImprovementLab(protocol.gateway.root)


def snapshot_for(protocol, name, args):
    protocol = _protocol(protocol, name)
    if name.startswith('intelligence.'):
        store = _store(protocol, args)
        state = store.snapshot()
        paths = [row['artifact'] for row in state['obligations']]
        if name == 'intelligence.obligate': paths.append(args['arguments']['artifact'])
        return {'state': state, 'sources': _sources(protocol, paths), 'files': _files(protocol, store.base),
                'events': store.events.read_text(encoding='utf-8') if store.events.exists() else ''}
    lab = _lab(protocol)
    before = {'files': _files(protocol, lab.base)}
    paths = []
    if name in {'lab.causal', 'lab.visual_guard'}: paths = [args['baseline'], args['variant' if name == 'lab.causal' else 'candidate']]
    elif name == 'lab.journey': paths = [args['path']]
    elif name == 'lab.curriculum': paths = [row['path'] for row in args['examples']]
    elif name == 'lab.resolve_uncertainty': paths = [args['target']]
    elif name == 'lab.rehearse':
        from ..experiment_studio import ExperimentStudio
        from ..installed_programs import InstalledPrograms
        manifest = ExperimentStudio(protocol.gateway.root).inspect(args['experiment_id'])
        paths = [str(Path(manifest['snapshot']) / args['script'])]
        before['manifest'] = manifest
        before['sessions'] = [str(p) for p in (InstalledPrograms(protocol.gateway.root).base / 'sessions').glob('*')]
    before['sources'] = _sources(protocol, paths)
    if name == 'lab.resolve_uncertainty':
        before['sources'].update(_sources(protocol, [lab.base / ('uncertainty-' + args['identity'] + '.json'),
            lab.base / ('instrument-' + args['instrument'] + '.json')]))
    return before


def _intelligence(protocol, name, args, value, before):
    from ..workspace_intelligence import _hash
    store = _store(protocol, args)
    state = store.snapshot()
    if _sources(protocol, list(before['sources'])) != before['sources']: return False
    if value.get('workId') != args['workId']: return False
    result, payload, prior = value['result'], args['arguments'], before['state']
    if name == 'intelligence.handoff':
        expected = {'schema': 'neyvia.workspace_handoff.v1', 'handoffId': result['handoffId'],
            'workId': store.work_id, 'objective': payload['objective'], 'protectedDecisions': payload['protected_decisions'],
            'answers': payload['answers'], 'artifacts': [{'path': row['artifact'], 'sha256': row['sha256'],
                'retrieval': str(store.root / row['artifact']), 'obligationId': row['id']} for row in prior['obligations']]}
        expected['integritySha256'] = _hash(expected)
        path = str(store.base / (store.work_id + '-handoff-' + result['handoffId'] + '.json'))
        return (state == prior and result == expected and _json(protocol, path) == expected and path not in before['files'] and
            _files(protocol, store.base) == {**before['files'], path: _measure_file(_path(protocol, path))})
    expected = deepcopy(prior)
    if name == 'intelligence.ask_self':
        row = {'id': result['id'], 'question': payload['question'].strip(), 'decision': payload['decision'].strip(),
            'answer': None, 'checks': [], 'revision': 0, 'status': 'open', 'source': 'agent_report', 'authorityGranted': False}
        if not row['id'].startswith('self-') or any(r['id'] == row['id'] for r in prior.get('selfQuestions', [])): return False
        expected.setdefault('selfQuestions', []).append(row)
        if result != row: return False
        event_kind, event_payload = 'self_question', row
    elif name == 'intelligence.answer_self':
        row = next(r for r in expected['selfQuestions'] if r['id'] == payload['question_id'])
        if row['revision'] != payload['expected_revision']: return False
        # Recompute criteria from actual bytes instead of accepting the owner's
        # recorded answer or its evaluator's verdict as the effect witness.
        observations = {}
        for obligation in state['obligations'][-200:]:
            path = _path(protocol, obligation['artifact'])
            digest = _measure_file(path)['sha256']
            criterion = obligation['criterion']
            passed = False
            if criterion['type'] == 'file_contains':
                passed = criterion['text'] in path.read_text(encoding='utf-8')
            elif criterion['type'] == 'json_path':
                try:
                    current = _json(protocol, path)
                    for part in criterion['path'].strip('.').split('.'):
                        current = current[part] if isinstance(current, dict) else current[int(part)]
                    passed = current == criterion['equals']
                except (ValueError, KeyError, IndexError, TypeError):
                    passed = False
            observations[obligation['id']] = {'id': obligation['id'], 'artifact': obligation['artifact'],
                'status': 'verified' if passed else 'failed', 'observedSha256': digest,
                'artifactChanged': digest != obligation['sha256'], 'claim': 'declared artifact criterion only'}
        evidence = [observations[i] for i in payload['checks']]
        verified = all(r['status'] == 'verified' and not r['artifactChanged'] for r in evidence)
        row.update(answer=payload['answer'].strip(), checks=payload['checks'], revision=row['revision'] + 1,
            status='supported_report' if verified else 'needs_recheck', evidence=evidence)
        if {k:v for k,v in result.items() if k != 'boundary'} != row: return False
        event_kind, event_payload = 'self_answer', {'questionId': payload['question_id'], 'answer': payload['answer'].strip(), 'checks': payload['checks']}
    elif name == 'intelligence.brief':
        old = prior.get('brief') or {}
        brief = state['brief']
        if old.get('revision', 0) != payload['expected_revision']: return False
        desired = {'revision': payload['expected_revision'] + 1, 'understanding': payload['understanding'].strip(),
            'assumptions': [s.strip() for s in payload['assumptions']] if 'assumptions' in payload else old.get('assumptions', []),
            'directions': [{k:v.strip() for k,v in d.items()} for d in payload['directions']] if 'directions' in payload else old.get('directions', []),
            'openQuestions': [s.strip() for s in payload['open_questions']] if 'open_questions' in payload else old.get('openQuestions', []),
            'selection': old.get('selection'), 'corrections': old.get('corrections', []), 'source': 'agent_proposal',
            'authorityGranted': False, 'updatedAt': brief['updatedAt']}
        if brief != desired or result != store.collaboration(): return False
        expected['brief'] = desired
        event_kind, event_payload = 'brief_proposed', {'understanding': payload['understanding'].strip()}
    else:
        key = 'rationales' if name == 'intelligence.rationale' else 'obligations'
        row = state[key][-1]
        if name == 'intelligence.rationale':
            desired = {'id': str(payload['element_id']), 'purpose': str(payload['purpose']),
                'protectedDecisions': list(payload.get('protected_decisions', [])), 'evidenceRefs': list(payload.get('evidence_refs', [])),
                'version': row['version'], 'createdAt': row['createdAt']}
            event_kind = 'rationale'
        else:
            artifact = _path(protocol, payload['artifact'])
            desired = {'id': row['id'], 'artifact': str(artifact.relative_to(store.root)), 'sha256': payload['sha256'],
                'criterion': payload['criterion'], 'scope': payload.get('scope', ''), 'createdAt': row['createdAt']}
            if _measure_file(artifact)['sha256'] != payload['sha256']: return False
            event_kind = 'obligation'
        if row != desired: return False
        expected[key].append(desired)
        event_payload = desired
    expected['revision'] += 1
    expected['integritySha256'] = _hash({k:v for k,v in expected.items() if k != 'integritySha256'})
    if state != expected: return False
    if name in {'intelligence.rationale', 'intelligence.obligate'} and result != state: return False
    events = store.events.read_text(encoding='utf-8')
    if not events.startswith(before['events']): return False
    return json.loads(events[len(before['events']):]) == {'kind': event_kind, 'revision': state['revision'], 'payload': event_payload}


def _lab_expected(protocol, name, args):
    lab = _lab(protocol)
    if name == 'lab.uncertainty':
        rows = [{'claim': r['claim'].strip(), 'experiment': r['experiment'].strip(),
            'probabilityWrong': r['probabilityWrong'], 'impact': r['impact'], 'cost': r['cost'],
            'priority': r['probabilityWrong'] * r['impact'] / r['cost'], 'estimateSource': 'caller_estimate'} for r in args['assumptions']]
        return {'assumptions': rows}, {'identity': args['identity'], 'ranked': sorted(rows, key=lambda r:-r['priority']), 'estimatesVerified': False}
    if name == 'lab.curriculum':
        rows = [{'path': str(_path(protocol, r['path']).relative_to(lab.root)),
            'sha256': _measure_file(_path(protocol, r['path']))['sha256'], 'family': r['family'].strip(), 'split': r['split']} for r in args['examples']]
        return {'examples': rows}, {'curriculumId': args['identity'], 'trainingCount': sum(r['split']=='train' for r in rows),
            'holdoutCount': sum(r['split']=='holdout' for r in rows), 'modelImprovementVerified': False}
    if name == 'lab.causal':
        a, ea = lab.document(args['baseline']); b, eb = lab.document(args['variant'])
        changed = sorted(k for k in a['conditions'].keys() | b['conditions'].keys() if a['conditions'].get(k) != b['conditions'].get(k))
        matched = changed == [args['factor']] and len(a['outcomes']) == len(b['outcomes'])
        return {'kind': 'causal_comparison', 'inputs': [ea, eb], 'changedFactors': changed,
            'status': 'matched_reported_trial' if matched else 'confounded', 'causalityProven': False,
            'pairedDeltas': [y-x for x,y in zip(a['outcomes'],b['outcomes'])] if matched else [],
            'limitation': 'Artifact contents are reported trials; repetitions, assignment and confounders require independent evaluation'}
    if name == 'lab.visual_guard':
        from PIL import Image
        checks = []
        with Image.open(_path(protocol,args['baseline'])) as first, Image.open(_path(protocol,args['candidate'])) as second:
            a,b = first.convert('RGBA'),second.convert('RGBA')
            for r in args['regions']:
                box = (r['x'],r['y'],r['x']+r['width'],r['y']+r['height'])
                checks.append({'region':r,'unchanged':a.crop(box).tobytes() == b.crop(box).tobytes()})
        return {'kind':'visual_guard','baselineSha256':_measure_file(_path(protocol,args['baseline']))['sha256'],
            'candidateSha256':_measure_file(_path(protocol,args['candidate']))['sha256'], 'checks':checks,
            'protectedPixelsUnchanged':all(r['unchanged'] for r in checks),'semanticQualityVerified':False}
    if name == 'lab.journey':
        rows,evidence = lab.document(args['path']); pending={}; delays=[]; errors=[]; transitions=[]; checkpoints={}; mismatches=[]; disconnected=False
        for r in rows:
            if r['kind']=='input': pending[r['id']]=r['atMs']
            elif r['kind']=='response': delays.append(r['atMs']-pending.pop(r['inputId']))
            elif r['kind']=='error': errors.append(r)
            else:
                transitions.append(r)
                if r['kind']=='disconnect': disconnected=True
                elif r['kind']=='reconnect': disconnected=False
                elif r['kind']=='checkpoint': checkpoints[r['checkpointId']]=r['stateHash']
                elif checkpoints.get(r['checkpointId']) != r['stateHash']: mismatches.append(r['checkpointId'])
        return {'kind':'journey','input':evidence,'durationMs':rows[-1]['atMs']-rows[0]['atMs'],'responseDelaysMs':delays,
            'unansweredInputs':list(pending),'errors':errors,'transitions':transitions,'continuityMismatches':mismatches,
            'disconnectedAtEnd':disconnected,'journeySuccessful':bool(delays) and not errors and not pending and not disconnected and not mismatches,
            'boundary':'reported trace analysis; recording provenance unverified'}


def _laboratory(protocol, name, args, value, before):
    lab = _lab(protocol)
    if _sources(protocol, list(before['sources'])) != before['sources']: return False
    if name == 'lab.rehearse':
        from ..installed_programs import InstalledPrograms
        from ..experiment_studio import ExperimentStudio
        host = InstalledPrograms(protocol.gateway.root)
        identity = value['session']['sessionId']
        folder = host._session(identity)
        if str(folder) in before['sessions'] or ExperimentStudio(protocol.gateway.root).inspect(args['experiment_id']) != before['manifest']: return False
        # A queued recipe alone is insufficient: the owning worker must execute.
        until = time.monotonic() + 10
        current = host.status(identity)
        while current['status'] in {'queued','starting','running'} and time.monotonic() < until:
            time.sleep(.05); current = host.status(identity)
        script = str(_path(protocol, Path(before['manifest']['snapshot']) / args['script']))
        return (current['status'] == 'completed' and current.get('exitCode') == 0 and
            current.get('pid',0) > 0 and current['arguments'] == [script, *args.get('arguments',[])] and
            _json(protocol,folder / 'source-recipe.json')['sourceSha256'] == before['sources'][script]['sha256'] and
            value['experimentId'] == args['experiment_id'] and value['promotion'] == 'not_performed')
    receipts = []
    if name in {'lab.uncertainty','lab.curriculum'}:
        spec,expected = _lab_expected(protocol,name,args)
        kind = name.split('.')[1]
        definition = lab.quality._definition(kind,args['identity'])
        path = str(lab.base / (kind + '-' + args['identity'] + '.json'))
        return (value == expected and definition['spec'] == spec and definition['sealed'] is True and path not in before['files'] and
            _files(protocol,lab.base) == {**before['files'],path:_measure_file(_path(protocol,path))})
    if name == 'lab.resolve_uncertainty':
        definition = lab.quality._definition('uncertainty',args['identity'])
        measurement = value['measurement']
        if not _receipt_check(protocol,lab.quality,measurement,_measurement(protocol,lab.quality,args['instrument'],args['target'])): return False
        expected = {'kind':'uncertainty_observation','identity':args['identity'],'assumption':args['assumption'],
            'definitionHash':definition['hash'],'measurement':measurement,'claimProven':False}
        receipts.append(measurement)
    else: expected = _lab_expected(protocol,name,args)
    receipts.append(value)
    additions = {r['receiptPath']:_measure_file(_path(protocol,r['receiptPath'])) for r in receipts}
    return (not set(additions)&set(before['files']) and len(additions)==len(receipts) and
        _files(protocol,lab.base)=={**before['files'],**additions} and _receipt_check(protocol,lab.quality,value,expected))


def checks_for(protocol, name, args):
    if name not in SUPPORTED: return []
    def verify(arguments,value,before):
        try:
            owner = _protocol(protocol,name)
            return (_intelligence if name.startswith('intelligence.') else _laboratory)(owner,name,arguments,value,before)
        except (OSError,ValueError,KeyError,TypeError,IndexError,StopIteration): return False
    return [{'name':'effect-'+name.replace('.','-'),'observer':True,'effect':True,
        'subjectKey':name+':'+str(args.get('workId') or args.get('identity') or args.get('experiment_id') or args.get('path') or args.get('baseline')),
        'observerTool':'fresh-task-evidence-frozen-definitions-and-worker','subject':{'tool':name},
        'expectation':'Exact durable task transition or recomputed local measurement with unchanged actual inputs; no semantic-quality promotion',
        'check':verify}]
