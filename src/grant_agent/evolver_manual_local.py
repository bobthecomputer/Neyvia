"""Deterministic manual compression through the real frozen paired engine.

This named domain measures lossless archival JSON compression and executable CL
roundtrips. It uses no model, and makes no claim about model task accuracy.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time

from .evolver_core import EvolverEngine, EvolutionError

DOMAIN = 'manual_json_local_v1'
PRETTY = 'manual-json-pretty-v1'
COMPACT = 'manual-json-compact-v1'
INVALID = 'manual-json-drop-guidance-v1'
REPO = Path(__file__).resolve().parents[2]


def domain_spec():
    # Distinct actual manuals, not copies relabelled as independent examples.
    paths = sorted((REPO / 'manuals').glob('*.manual.json'), key=lambda p:(p.stat().st_size,p.name))[:48]
    if len(paths) != 48:
        raise EvolutionError('Local compression requires 48 distinct actual manuals')
    panels = [{'id':'manual-local-'+str(panel), 'role':'discovery' if panel<2 else 'held_out',
        'items':[{'id':p.stem,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths[panel*12:(panel+1)*12]]}
        for panel in range(4)]
    return {'panels':panels, 'judges':[str(Path(__file__).resolve()), str(REPO/'src/grant_agent/cl/manuals.py'),
        str(REPO/'src/grant_agent/cl/parser.py'),str(REPO/'src/grant_agent/cl/schema.py'),
        str(REPO/'src/grant_agent/manual_contracts.py'),*map(str,paths)],
        'objectives':{'tokenRatio':{'direction':'min','tolerance':0,'noise':0},
            'roundtrip':{'direction':'max','tolerance':0,'noise':0}},
        'promotion':{'alpha':.05,'min_pairs':12,'max_trials':2,'max_evaluations':120,
            'max_seconds':300,'seed':48826},'hard_gates':['exactSemantics','compiledRoundtrip']}


class ManualCompressionEvaluator:
    def __init__(self, root):
        self.root = Path(root).resolve()
        from .native_tools import NativeToolRegistry
        registry = NativeToolRegistry(self.root)
        self.metadata = {name:{'mutability_class':spec.mutability_class} for name,spec in registry._specs.items()}

    def __call__(self, genome, item, seed):
        from .cl.manuals import manual_to_cl, cl_to_manual
        from .cl.tokens import count_tokens
        from .manual_contracts import validate_structure
        path = Path(item['path']).resolve()
        if not path.is_relative_to(REPO/'manuals') or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise EvolutionError('Frozen actual manual input changed')
        original = json.loads(path.read_text(encoding='utf-8'))
        recipe = genome['text']
        if recipe not in {PRETTY, COMPACT, INVALID}:
            raise EvolutionError('Unknown immutable local compression recipe')
        candidate = json.loads(json.dumps(original))
        if recipe == INVALID:
            for chapter in candidate['chapters'].values(): chapter['guidance']=[]
        rendered = json.dumps(candidate,ensure_ascii=False,indent=2) if recipe==PRETTY else json.dumps(candidate,ensure_ascii=False,separators=(',',':'))
        decoded = json.loads(rendered)
        validate_structure(decoded)
        # Compile actual typed actions/procedures and parse them back; preserving
        # just a name or a field count cannot satisfy these hard gates.
        compiled = manual_to_cl(decoded,self.metadata)
        roundtrip = cl_to_manual(compiled)
        exact, compiled_exact = decoded==original, roundtrip==original
        baseline_tokens = count_tokens(json.dumps(original,ensure_ascii=False,indent=2))
        tokens = count_tokens(rendered)
        identity = hashlib.sha256(json.dumps(genome,sort_keys=True).encode()).hexdigest()
        directory = self.root/'.neyvia/evolver-manual-artifacts'/identity
        directory.mkdir(parents=True,exist_ok=True)
        artifact = directory/(item['id']+'-'+str(seed)+'.json')
        artifact.write_text(rendered,encoding='utf-8',newline='\n')
        compiled_path = artifact.with_suffix('.cl')
        compiled_path.write_text(compiled,encoding='utf-8',newline='\n')
        return {'objectives':{'tokenRatio':tokens/baseline_tokens,'roundtrip':int(exact and compiled_exact)},
            'hard_gates':{'exactSemantics':exact,'compiledRoundtrip':compiled_exact},
            'receipt':{'inputPath':str(path),'inputSha256':item['sha256'],'artifact':str(artifact),
                'artifactSha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'compiledPath':str(compiled_path),
                'compiledSha256':hashlib.sha256(compiled_path.read_bytes()).hexdigest(),
                'tokens':tokens,'baselineTokens':baseline_tokens,'seed':seed,'recipe':recipe,
                'boundary':'lossless manual bytes and executable CL semantics; model accuracy unmeasured'}}


def run(root, max_trials=1, output=None):
    root = Path(root).resolve()
    if not root.is_relative_to(REPO): raise EvolutionError('Run root must be in the owned worktree')
    engine = EvolverEngine(root/'.neyvia/evolver.sqlite3')
    spec = domain_spec()
    engine.establish_domain(DOMAIN,**spec)
    baseline = engine.register_genome(DOMAIN,{'kind':'text','text':PRETTY},provenance={'source':'lossless actual archival manual JSON'})
    current = engine.status(DOMAIN)['domains'][0]
    if not current.get('incumbent'): engine.set_incumbent(DOMAIN,baseline['id'])
    candidate = engine.register_genome(DOMAIN,{'kind':'text','text':COMPACT},parent_id=baseline['id'],
        operator='deterministic-whitespace-compression',provenance={'model':None,'selection':'generic recipe; no heldout feedback'})
    trial = engine.evaluate_candidate(DOMAIN,candidate['id'],ManualCompressionEvaluator(root))
    summary = {'schema':'neyvia.evolver-local-manual-run.v1','root':str(root),'model':None,
        'sampling':'Exact same real manual and task/order seed for incumbent and candidate; disjoint heldout manual files',
        'domains':{DOMAIN:{'baseline':baseline['id'],'trials':[trial],'state':engine.status(DOMAIN)}},
        'maxTrials':max_trials,'finished':time.time(),'boundary':'actual lossless manual compression; no model task-accuracy or public promotion claim'}
    target = Path(output).resolve() if output else root/'.neyvia/evolver-last-run.json'
    if not target.is_relative_to(root): raise EvolutionError('Output must be within owned run root')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
    return summary
