"""Thin native editor adapters; all predicates and retention run in scene_core.

Transcription is deterministic for identical native state: render paths, run ids and
counters stay in the caller's source handle (source['_latestRender']), never in the
Scene, so the shared core can verify an exact rollback by scene sha256.
Blender callers pass budget guards {'silhouette_quality': 'min'} to scene.improve.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid

from . import Adapter
from ..neyvia_gamedev import service_for

MANUAL=Path(__file__).resolve().parents[3]/'manuals/cl/laya-3d.cl'
ENGINES={'blender','godot','unity','roblox'}
SCENE_KEYS=('surface','nodes','truncated','unknown','measurements')
DEFAULT_TARGETS={'closedSurface':False,'smooth':False,'uv':False,'unitScale':False,
                 'originCentered':False,'singleComponent':False,'symmetric':False,
                 'texture':False,'texelDensity':0,'stretch':False,'refineSilhouette':False,
                 'noIntersections':False,'quadFlow':False}


def vocabulary(domain):
    return [r for line in MANUAL.read_text(encoding='utf-8').splitlines()
            if line.startswith('-- @predicate ') for r in [json.loads(line[14:])]
            if domain in r.get('domains',[])]


def call(source,action,args,*,timeout=240):
    service=service_for(source['root'])
    session=next((r for r in service.sessions()['sessions'] if r['sessionId']==source['sessionId']),None)
    if not session or session['engine']!=source['domain'] or session['context']!='Edit':
        raise ValueError('Exact Edit session for the requested engine is required')
    receipt=service.action({'sessionId':session['sessionId'],'action':action,'args':args})
    deadline=time.monotonic()+timeout
    while receipt['status'] in {'queued','running'}:
        if time.monotonic()>deadline:
            raise TimeoutError('Native '+action+' did not finish; inspect the editor before retrying')
        time.sleep(.05)
        receipt=service.receipt(receipt['requestId'])
    if receipt['status']!='succeeded':
        raise RuntimeError(receipt.get('error') or receipt['status'])
    return receipt['result']


def _observe(source):
    raw=call(source,'transcribe',{'targets':source.get('targets',{})})
    # Engines may serialize unrelated empty result fields (Unity JsonUtility); keep Scene facts only.
    scene={k:raw[k] for k in SCENE_KEYS if k in raw}
    if not isinstance(scene.get('nodes'),list):
        raise ValueError('Native transcribe returned no node list')
    targets={**DEFAULT_TARGETS,**source.get('targets',{})}
    for node in scene['nodes']:
        node['measurements']=node.pop('facts',node.get('measurements',{}))
        node.setdefault('attributes',{})['targets']=targets
    return scene


def transcribe(source):
    scene=_observe(source)
    if source['domain']=='blender' and source.get('renders'):
        # Fresh directories per render (the bridge refuses reuse); paths stay out of the Scene.
        run=source.setdefault('_run',uuid.uuid4().hex)
        counter=source.get('_renderCount',0); source['_renderCount']=counter+1
        render=call(source,'canonical',{'path':f'laya3d/{run}/view-{counter}',**({'framing':source['_framing']} if '_framing' in source else {})})
        source.setdefault('_framing',render['framing'])
        source.setdefault('_baselineViews',render['views'])
        # Source reference must be masks from declared matching camera framing;
        # otherwise this measures parent silhouette preservation, never source fidelity.
        reference=source.get('referenceViews',source['_baselineViews'])
        if [v['view'] for v in reference]!=[v['view'] for v in render['views']]:
            raise ValueError('Canonical reference views differ')
        scores=[]
        for before,after in zip(reference,render['views']):
            if before['pixels']!=after['pixels']: raise ValueError('Mask resolutions differ')
            a,b=int(before['maskHex'],16),int(after['maskHex'],16)
            scores.append((a&b).bit_count()/max((a|b).bit_count(),1))
        scene['metrics']={'silhouette_quality':min(scores)}
        # Mask digests are pixel content; PNG bytes carry render-time metadata.
        scene['provenance']={'maskSha256':[hashlib.sha256(v['maskHex'].encode()).hexdigest() for v in render['views']],
                             'views':[v['view'] for v in render['views']],
                             'silhouetteReference':'source' if 'referenceViews' in source else 'original-model',
                             'framing':render['framing'],'viewIoU':scores}
        source['_latestRender']=render
        source.setdefault('_renders',[]).append([v['path'] for v in render['views']])
        for node in scene['nodes']:
            if node['kind']=='mesh': node['measurements']['silhouetteMatch']=min(scores) if 'referenceViews' in source else None
    return scene


def checkpoint(source):
    if source['domain']=='blender':
        if not source.get('renders') or '_baselineViews' not in source:
            raise ValueError('Blender improvement requires canonical renders before checkpoint')
        return call(source,'snapshot',{'path':'laya3d/'+uuid.uuid4().hex+'.blend'})
    # Native engine fixes are guarded property edits, captured from fresh Scene facts.
    return _observe(source)


def _scales(scene):
    return {n['id']:n['attributes']['scale'] for n in scene['nodes'] if n.get('attributes',{}).get('scale') is not None}


def restore(source,snapshot):
    if source['domain']=='blender': return call(source,'restore',snapshot)
    current=_scales(_observe(source))
    for node,scale in _scales(snapshot).items():
        if current.get(node)!=scale:
            _scale(source,node,scale)
    if _scales(_observe(source))!=_scales(snapshot):
        raise RuntimeError('Native scale restore did not reproduce the checkpoint')


def _scale(source,node,scale):
    if source['domain']=='godot':
        return call(source,'edit',{'node':node,'property':'scale','value':scale})
    if source['domain']=='unity':
        return call(source,'edit',{'path':node,'component':'Transform','property':'m_LocalScale','vector':scale})
    raise ValueError('Roblox fixes require an installed live Studio session')


def fix(source,finding):
    pattern=finding['fix']; operation=pattern['action'].split('.',1)[1]
    if source['domain']!='blender':
        if pattern['action']!='engine.scale': raise ValueError('Only engine.scale is a native engine fix')
        return _scale(source,finding['node'],[1,1,1])
    arguments=dict(pattern.get('arguments',{}))
    if operation=='upscale_texture': arguments['resolution']=source.get('targets',{}).get('textureResolution',1024)
    return call(source,'mesh_fix',{'object':finding['node'],'operation':operation,**arguments})


def make_adapter(domain):
    if domain not in ENGINES: raise ValueError('Unknown native engine domain: '+domain)
    actions={r['fix']['action'] for r in vocabulary(domain)}-{'review'}
    if domain=='roblox': actions=set()  # Studio is required; no inferred property repair.

    def observe(source):
        if source.get('domain',domain)!=domain: raise ValueError('Source domain differs from adapter domain')
        source['domain']=domain
        return transcribe(source)
    return Adapter(transcribe=observe, vocabulary=lambda:vocabulary(domain),
                   fixes={action:fix for action in actions}, checkpoint=checkpoint, restore=restore)
