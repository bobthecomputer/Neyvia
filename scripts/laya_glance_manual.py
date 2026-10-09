"""Author/compile the shared Scene API's executable manual (no test files)."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.cl.manuals import manual_to_cl,cl_to_manual
from grant_agent.neyvia_laya_capabilities import DEFINITIONS

source=ROOT/'manuals/cl/laya-glance.cl'
bugs=[line for line in source.read_text(encoding='utf-8').splitlines() if line.startswith('-- @bug ')]
names={'scene.transcribe','scene.vocabulary','laya.judge','scene.improve','scene.episode','laya.glance','laya.glance_learn','laya.glance_contracts','laya.glance_proof','laya.glance_lesson'}
definitions=[r for r in DEFINITIONS if r[0] in names]
def strict(props,required):
    # Same non-empty rule as the native catalog: required strings are not "", untyped values not null/"".
    rules={k:{'not':{'enum':['']}} if props[k].get('type')=='string' else {'not':{'enum':[None,'']}} for k in required if props[k].get('type')=='string' or props[k]=={}}
    schema={'type':'object','properties':props,'required':required}
    return {**schema,'allOf':[{'properties':rules}]} if rules else schema
schemas={'neyvia.'+name:strict(props,required) for name,_,props,required in definitions}
actions={name.replace('.','-'):{'tool':'neyvia.'+name,'schema':'neyvia.'+name,'returns':{'type':'object'},
           'pre':'Registered adapter; source is observed data; mutations need caller authority',
           'effect':description,'reversible':name not in {'scene.episode','laya.glance_learn','laya.glance_lesson'}}
         for name,description,_,_ in definitions}
checks={'live-predicates':{'tool':'neyvia.laya.glance_contracts','args':{},
                         'expect':{'op':'eq','path':'passed','value':True}},
        'pixel-before-after':{'tool':'neyvia.laya.glance_proof','args':{},
                         'expect':{'op':'eq','path':'passed','value':True}},
        # SDK seam: an out-of-repo caller (the trading repo) brings its own raw scene and vocabulary.
        # The code-shaped value is compared as text and never evaluated, so exactly one finding fires.
        'external-predicates':{'tool':'neyvia.laya.judge','args':{'domain':'sdk-probe','record':False,
                         'scene':{'nodes':[{'id':'book','kind':'position','attributes':{'symbol':'BTC-USD'},'measurements':{'exposure':0.31,'limit':0.25}},
                                           {'id':'feed','kind':'quote','attributes':{'note':"__import__('os').system('calc')"},'measurements':{'ageSeconds':2}}]},
                         'predicates':[{'id':'risk-limit-breach','condition':{'all':[{'field':'kind','op':'eq','value':'position'},{'field':'measurements.exposure','op':'gt','value':0.25}]},
                                        'severity':'error','evidence':['measurements.exposure','measurements.limit'],'fix':{'action':'config.reduce-size','arguments':{'review':'human'}}},
                                       {'id':'code-as-data','condition':{'field':'attributes.note','op':'eq','value':'0'},
                                        'severity':'error','evidence':['attributes.note'],'fix':{'action':'review','arguments':{}}},
                                       {'id':'stale-data','condition':{'all':[{'field':'kind','op':'eq','value':'quote'},{'field':'measurements.ageSeconds','op':'gt','value':60}]},
                                        'severity':'warning','evidence':['measurements.ageSeconds'],'fix':{'action':'data.refresh','arguments':{}}}]},
                         'expect':{'op':'schema','path':'findings','schema':{'type':'array','minItems':1,'maxItems':1,
                                   'items':{'type':'object','required':['predicate','node'],'properties':{'predicate':{'const':'risk-limit-breach'},'node':{'const':'book'}}}}}}}
chapter={'title':'One Scene core: transcribe, predicates, instant examples and guarded improvement',
         'state':{},'actions':actions,'checks':checks,
         'procedures':{'prove-scenes':{'goal':'Exercise actual headless DOM/canvas observations and compare before/after defect outcomes',
           'inputs':{'type':'object','properties':{}},'steps':[{'action':'laya-glance_contracts','args':{},'save':'observed','check':'live-predicates'}]},
           'prove-pixels':{'goal':'Glance the recorded before/after fix captures from pixels: the black PDF page, see-through panels and clipped chips are caught before and absent after',
           'inputs':{'type':'object','properties':{}},'steps':[{'action':'laya-glance_proof','args':{},'save':'proof','check':'pixel-before-after'}]},
           'prove-sdk-seam':{'goal':'Judge a caller-transcribed scene with caller-supplied predicates (the out-of-repo SDK seam): one exact finding, code-shaped text stays data',
           'inputs':{'type':'object','properties':{}},'steps':[{'action':'laya-judge','args':checks['external-predicates']['args'],'save':'verdict','check':'external-predicates'}]}},
         'judge':{},'pitfalls':[{'failure':'Missing style or geometry fact','recovery':'Preserve unknown and request one model look; never infer a clean screen.'}],
         'frontier':['UI fixes edit a web source tree, never a live window: CSS/token overrides computed from the finding and recorded library patches (laya-ui-fix.cl); improve keeps one only when a fresh private render shows strictly fewer findings with no guard regression. A perception scene or screenshot alone stays proposal-only. Engine adapters register separately.',
                     'Pixel-only recall is low for overlap (icon collisions), off-screen controls and phone peek sheets whose foreign text lies wholly inside the sheet; a clean pixel verdict is therefore never admitted and escalates to one model look.',
                     'A screenshot glance takes about 0.5 s (OCR ~0.2 s, pixel facts ~0.25 s, judge ~6 ms); the DOM+screenshot gate glance adds the render.'],
         'guidance':['Broken means a see-through surface, clipped text, raw error, encoded path or internal id, blank expected render, unintended overlap, unreadable contrast, or an off-screen control. Crisp predicates cite observed facts; fuzzy judgement uses instant episodes at nominal 0.95. No training runs or new heads.',
                     'Transcribe from the perception DOM graph when the app is live; a screenshot alone is read by local OCR plus measured pixel facts. With both, the screenshot cross-checks DOM coverage and fills contrast, and pixel findings count only where their calibrated precision reaches 0.95.',
                     'Teach with laya.glance_lesson (one node, effective on the next glance) or laya.glance_learn (one labelled screenshot, updates calibration). Lessons apply only to text-intrinsic predicates; see-through, off-screen and blank renders depend on layout.']}
manual={'schema':'neyvia.manual.v1','id':'laya-glance','kind':'environment','clVersion':'1.1','schemas':schemas,
        'tool_metadata':{'neyvia.'+name:{'mutability_class':'artifact_write' if name in {'scene.episode','laya.glance_learn','laya.glance_lesson'} else 'external_action' if name in {'scene.improve','laya.glance_contracts'} else 'read'} for name in names},
        'chapters':{'scene':chapter},
        'proofs':{'area':'scene-core','contracts':[{'id':'layag.scene-predicates','phase':'invariant',
          'checkedAt':['grant_agent.scene_core.judge','grant_agent.laya_glance_contracts.observe'],
          'impact':['src/grant_agent/scene_core','src/grant_agent/laya_glance.py','src/grant_agent/perception_scene.js'],
          'claim':'Actual before/after DOM and canvas observations bind typed defects to nodes and fixes.'},
          {'id':'layag.pixel-before-after','phase':'invariant',
          'checkedAt':['grant_agent.laya_glance_proof.run','grant_agent.laya_glance.glance'],
          'impact':['src/grant_agent/laya_glance_image.py','src/grant_agent/laya_glance.py','src/grant_agent/laya_glance_proof.py','manuals/cl/laya-glance.cl'],
          'claim':'From pixels alone, the black PDF page, see-through panels and clipped chips are caught on recorded before captures and absent on the after captures.'},
          {'id':'core.sdk-seam','phase':'invariant',
          'checkedAt':['grant_agent.scene_core.normalize','grant_agent.scene_core.check_predicates','grant_agent.scene_core.judge'],
          'impact':['src/grant_agent/scene_core/__init__.py','src/grant_agent/neyvia_laya_capabilities.py','src/neyvia_sdk/client.py','packages/neyvia-sdk/index.js'],
          'claim':'An out-of-repo caller judges its own raw scene with its own predicates through the shared judge; predicates are validated data and never executed.'}]}}
metadata=manual.pop('tool_metadata')
manual.pop('clVersion')
cl=manual_to_cl(manual)+'\n'+'\n'.join(bugs)+'\n'
source.write_text(cl,encoding='utf-8',newline='\n')
cl_to_manual(cl)  # parse check; the artifact is written by the canonical compiler
import subprocess
subprocess.run([sys.executable,str(ROOT/'scripts/cl_compile_manuals.py'),'--source-file',str(source)],check=True,cwd=ROOT)
index_path=ROOT/'config/neyvia_manuals.json'
index=json.loads(index_path.read_text(encoding='utf-8'))
if not any(r['id']=='laya-glance' for r in index['manuals']):
    index['manuals'].append({'id':'laya-glance','path':'manuals/laya-glance.manual.json',
                            'description':'Shared Scene core, UI defect vocabulary and instant episodic admission',
                            'clSource':'manuals/cl/laya-glance.cl'})
    index_path.write_text(json.dumps(index,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
print('Authored laya-glance manual and preserved',len(bugs),'executable predicate definitions')
