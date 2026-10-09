"""Agent/App Factory/taste-loop access to bounded LAYA capabilities."""
from __future__ import annotations
import hashlib
import json
from . import laya_curriculum as curriculum
from . import laya_components as components

TEXT = {'type': 'string', 'maxLength': 16000}
DEFINITIONS = [
    ('scene.transcribe', 'Transcribe one domain source through its registered adapter into a shared CL Scene.', {'domain': TEXT, 'source': {'type': 'object'}}, ['domain','source']),
    ('scene.vocabulary', 'Read the registered domain predicates and named fix patterns.', {'domain': TEXT}, ['domain']),
    ('laya.judge', 'Apply one shared predicate evaluator and instant episodic admission to a Scene. Out-of-repo callers may pass a raw scene with its domain and their own predicates (same shape, data only, never executed).',
     {'scene': {'type': 'object'}, 'user': TEXT, 'domain': TEXT, 'predicates': {'type': 'array', 'maxItems': 500, 'items': {'type': 'object'}},
      'record': {'type': 'boolean'}}, ['scene']),
    ('scene.improve', 'Apply only explicitly budgeted reversible adapter fixes; trading is human review only.', {'domain': TEXT, 'source': {'type': 'object'}, 'budget': {'type': 'object'}}, ['domain','source','budget']),
    ('scene.episode', 'Write a labelled Scene episode immediately without training.', {'scene': {'type': 'object'}, 'label': {}, 'reason': TEXT, 'source': TEXT, 'user': TEXT, 'layer': {'enum':['corrective','personal']}}, ['scene','label','reason','source']),
    ('laya.glance_contracts', 'Observe real headless DOM/canvas cases for the CL scene predicates.', {}, []),
    ('laya.glance', 'Apply the CL broken-UI vocabulary to a perception scene or immutable handle. Unknown facts request one model look.',
     {'scene': {'type': 'object'}, 'handle': TEXT, 'screenshot': TEXT, 'fuzzy': {'type': 'boolean'}}, []),
    ('laya.glance_proof', 'Glance the recorded before/after fix captures from pixels alone: black PDF page, see-through panels, clipped composer chips.', {}, []),
    ('laya.glance_lesson', 'Teach one node instantly: broken adds the defect to similar text, fine suppresses a false alarm. No training.',
     {'scene': {'type': 'object'}, 'node': TEXT, 'predicate': {'enum': ['clipped-text', 'raw-error', 'encoded-path', 'internal-id', 'overlap', 'unreadable-contrast']},
      'label': {'enum': ['broken', 'fine']}, 'reason': TEXT, 'source': TEXT}, ['scene', 'node', 'predicate', 'label', 'reason', 'source']),
    ('laya.glance_learn', 'Write one labelled screenshot episode; no training or head consolidation.',
     {'screenshot': TEXT, 'label': {'enum': ['broken', 'fine']}, 'reason': TEXT, 'source': TEXT, 'surface': TEXT},
     ['screenshot', 'label', 'reason', 'source']),
    ('efficiency.laya_learn', 'Write a local episode immediately; explicit replay is separate from calibrated novel-case admission.',
     {'domain': TEXT, 'input': {}, 'label': {}, 'source': TEXT, 'user': TEXT,
      'layer': {'type': 'string', 'enum': ['personal', 'corrective']}, 'weight': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1}, 'evidence': {'type': 'object'}}, ['domain', 'input', 'label', 'source']),
    ('efficiency.laya_query', 'Query personal then corrective episodes, abstaining on conflicting or uncalibrated regions.',
     {'domain': TEXT, 'input': {}, 'user': TEXT, 'labels': {'type': 'array'}}, ['domain', 'input']),
    ('efficiency.laya_forget', 'Append a provenance tombstone, removing matching episodes from subsequent decisions.', {'source': TEXT}, ['source']),
    ('efficiency.laya_ingest', 'Ingest local Paul votes and incoming label files with idempotent provenance.', {}, []),
    ('efficiency.laya_experience', 'Record weak kept/reverted, edit, acceptance, reask, route and verifier signals; never self-certifies a prediction.',
     {'domain': TEXT, 'input': {}, 'signal': TEXT, 'source': TEXT, 'user': TEXT, 'value': {}, 'elapsedSeconds': {'type': 'number'}}, ['domain', 'input', 'signal', 'source']),
    ('efficiency.laya_route', 'Retrieve learned manual/action/check/procedure candidates. Abstain unless independent calibration admits the route; no execution authority.',
     {'intent': TEXT, 'consultLaya': {'type': 'boolean'}}, ['intent']),
    ('efficiency.laya_outcome', 'Estimate a step outcome from receipt evidence with a separately calibrated learned head. Never establishes completion authority.',
     {'receipt': {'type': 'object'}}, ['receipt']),
    ('efficiency.laya_training', 'Read learned corpus coverage, held-out metrics and current artifact fingerprints. Does not start training.', {}, []),
    ('component.find', 'Find component patterns learned from allowed public sources; short notes and source/license attribution, no copied library code.',
     {'intent': TEXT, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 8}}, ['intent']),
    ('component.invent', 'Compose an original interactive draft from learned patterns and separate Paul conditioning. Returns code, composition, review limits and feel; never a published component.',
     {'intent': TEXT, 'seed': {'type': 'integer', 'minimum': 0, 'maximum': 1000}}, ['intent']),
    ('component.feel', 'Review code or supplied rendered metrics, preserving separate corrective and personal layers. Caller measurements are not fresh host proof.',
     {'code': {'type': 'string', 'maxLength': 200000}, 'render': {'type': 'object'}, 'intent': TEXT,
      'consultLaya': {'type': 'boolean'}}, []),
]


def call(name, args, root=None, *, workspace=None):
    try:
        from .laya_instant import store
        if name in {'scene.transcribe','scene.vocabulary','laya.judge','scene.improve','scene.episode'}:
            from . import scene_core
            base = root or curriculum.REPO
            if name in {'scene.transcribe','scene.improve'} and args['domain'] in {'blender','godot','unity','roblox','laya3d'}:
                source = {k:v for k,v in args['source'].items() if not k.startswith('_')}
                args = {**args, 'source': {**source, 'root':str(base), 'domain':args['domain'],
                                          '_allowBuild':name=='scene.improve'}}
            if name == 'scene.transcribe':
                source = args['source']
                if args['domain']=='ui' and 'layer' in source and 'source' in source:
                    if workspace is None:
                        raise ValueError('Live UI transcription requires the Neyvia workspace host')
                    from .neyvia_perception import observe
                    from . import manual_state
                    observed = observe(workspace, source)
                    source = manual_state.read(base / '.neyvia/perception', observed['handle'])['value']
                return scene_core.transcribe(args['domain'],source)
            if name == 'scene.vocabulary':
                return {'domain':args['domain'],'predicates':scene_core.vocabulary(args['domain'])}
            if name == 'laya.judge':
                scene = args['scene']
                if scene.get('schema') != scene_core.SCHEMA or 'sha256' not in scene:
                    # A caller-transcribed raw scene (SDK seam): bind it here, judge it with its own predicates.
                    scene = scene_core.normalize(args.get('domain') or scene.get('domain'), scene)
                return scene_core.judge(scene,args.get('predicates'),root=base,user=args.get('user',''),
                                        record=args.get('record',True))
            if name == 'scene.improve':
                budget = args['budget']
                if args['domain']=='blender':  # Mesh repairs never trade away the rendered silhouette.
                    budget = {**budget, 'guards': {'silhouette_quality':'min', **budget.get('guards',{})}}
                result = scene_core.improve(args['domain'],args['source'],budget,root=base)
                if args['domain']=='laya3d':
                    from .scene_core.image_model import persist
                    result['modelPath']=persist(args['source'])
                return result
            return scene_core.episode(base,**args)
        if name == 'laya.glance_contracts':
            from .laya_glance_contracts import observe
            return observe()
        if name == 'laya.glance_proof':
            from .laya_glance_proof import run
            return run()
        if name == 'laya.glance_lesson':
            from pathlib import Path
            from . import laya_glance
            scene = laya_glance.transcribe(args['scene'])
            return laya_glance.learn_node(Path(root or curriculum.REPO), scene, args['node'], args['predicate'], args['label'],
                                          args['reason'], args['source'])
        if name in {'laya.glance', 'laya.glance_learn'}:
            from pathlib import Path
            from . import laya_glance, manual_state
            from .neyvia_perception import confined
            base = Path(root or curriculum.REPO)
            screenshot = str(confined(base, args['screenshot'])) if args.get('screenshot') else None
            if name == 'laya.glance_learn':
                return laya_glance.learn(base, screenshot, args['label'], args['reason'], args['source'], surface=args.get('surface', ''))
            if args.get('scene') and args.get('handle') or not (args.get('scene') or args.get('handle') or screenshot):
                raise ValueError('Supply one scene or perception handle, or a screenshot alone')
            scene = args.get('scene')
            if args.get('handle'):
                scene = manual_state.read(base / '.neyvia/perception', args['handle'])['value']
            return laya_glance.glance(scene, root=base, screenshot=screenshot, fuzzy=args.get('fuzzy', False))
        if name in {'efficiency.laya_learn', 'efficiency.laya_query', 'efficiency.laya_forget'}:
            return getattr(store(str(root or curriculum.REPO)), name.rsplit('_', 1)[-1])(**args)
        if name in {'efficiency.laya_ingest', 'efficiency.laya_experience'}:
            from . import laya_instant_ingest
            return getattr(laya_instant_ingest, name.rsplit('_', 1)[-1])(root or curriculum.REPO, **args)
        if name == 'efficiency.laya_route':
            instant = store(str(root or curriculum.REPO)).query('routing', args['intent'])
            if not instant['escalate'] or instant.get('conflict'):
                return instant
            return curriculum.route(args['intent'], args.get('consultLaya', False))
        if name == 'efficiency.laya_outcome':
            receipt = args['receipt']
            result = receipt.get('result', {})
            verdict = curriculum.classify(curriculum.load('receipt-outcome'), curriculum.receipt_text(result))
            instant = store(str(root or curriculum.REPO)).query('outcomes', curriculum.outcome_input(receipt))
            if not instant['escalate'] or instant.get('conflict'):
                verdict = instant
            if not receipt.get('proofs') or not isinstance(receipt.get('ok'), bool):
                verdict.update(answer=None, confidence=0, escalate=True, reason='missing-independent-receipt-proof')
            return {**verdict, 'advisoryOnly': True}
        if name == 'efficiency.laya_training':
            report = json.loads((curriculum.REPO / 'scripts/evidence/LAYAT-capability-metrics.json').read_text(encoding='utf-8'))
            vision_report = curriculum.REPO / 'scripts/evidence/LAYAT-vision-metrics.json'
            if vision_report.is_file():
                report['layout'] = json.loads(vision_report.read_text(encoding='utf-8'))['corrective']
            return {'areas': report, 'gate': .95, 'baseWeightsChanged': False,
                    'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in curriculum.ARTIFACTS.glob('*.json')}}
        if name == 'component.find':
            result = components.find(args['intent'], args.get('limit', 4))
            for row in result['matches']:
                if 'renderRepresentation' in row:
                    row['renderRepresentation'] = {k: v for k, v in row['renderRepresentation'].items() if k != 'imageEmbedding'}
            return result
        if name == 'component.invent':
            return components.invent(args['intent'], args.get('seed', 0), root=root)
        if name == 'component.feel':
            return components.feel(args.get('code', ''), args.get('render'), args.get('intent', ''), root,
                                   args.get('consultLaya', False))
    except (OSError, ValueError, KeyError) as exc:
        return {'available': False, 'escalate': True, 'accepted': False, 'reason': type(exc).__name__ + ': ' + str(exc)[:200]}
    raise KeyError(name)
