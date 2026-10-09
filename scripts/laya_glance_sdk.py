"""Exercise the actual SDK facade against fresh native tool dispatch."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.scene_core import SceneClient
from grant_agent.neyvia_gateway import NeyviaToolGateway
from grant_agent.neyvia_manuals import unwrap
gateway=NeyviaToolGateway(ROOT/'.agent_control/layag-sdk',allow_mutations=True,permission_mode='workspace',managed_capabilities=False)
receipts=[]
run=str(time.time_ns())
def native(tool,args):
    r=gateway.call_native(tool,args,action_id='layag-sdk-'+run+'-'+str(len(receipts)))
    receipts.append(r)
    if not r.get('ok'):raise RuntimeError(str(r))
    return unwrap(r)
sdk=SceneClient(native)
scene=sdk.transcribe('ui',{'nodes':[{'id':'chip','role':'button','text':'Read only','facts':{'clippedText':True}}]})
rules=sdk.vocabulary('ui')
result=sdk.judge(scene)
learned=sdk.episode(scene,'broken','SDK explicit label','sdk-proof-'+run)
import shutil
shot=ROOT/'.agent_control/layag-sdk/before-chips.png'
shot.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2('D:/NeyviaRuns/ui-fix/pairs/shell-before-light-laya-main.png',shot)
pixels=sdk.glance(screenshot='before-chips.png')
chip=next(b for b in pixels['bugs'] if b['type']=='clipped-text')
from grant_agent.laya_glance import transcribe as ui_scene
seen=ui_scene({'image':str(shot)})
lesson=sdk.lesson(seen,chip['node'],'clipped-text','fine','SDK proof: suppress then restore','sdk-lesson-'+run)
after_lesson=sdk.glance(screenshot='before-chips.png')
review=sdk.improve('ui',{'nodes':[{'id':'chip','role':'button','text':'Read only','facts':{'clippedText':True}}]}, {'max_steps':0,'max_seconds':10,'allowed_fixes':[]})
report={'mutationStatuses':[r.get('operationStatus') for r in receipts if 'operationStatus' in r],'passed':all(r.get('operationStatus')=='verified' for r in receipts if 'operationStatus' in r) and result.get('admitted',False) and any(f['predicate']=='clipped-text' for f in result.get('findings',[])) and chip['node'] not in {b['node'] for b in after_lesson['bugs'] if b['type']=='clipped-text'},
        'boundary':'SDK facade with fresh real Neyvia gateway dispatch; no HTTP transport substitution claim',
        'tools':[r.get('tool') for r in receipts],
        'pixelGlance':{'admitted':pixels['admitted'],'bugs':sorted({b['type'] for b in pixels['bugs']}),'ms':pixels.get('glanceMs')},
        'lesson':{'node':chip['node'],'suppressedNext':chip['node'] not in {b['node'] for b in after_lesson['bugs'] if b['type']=='clipped-text'},
                  'lessons':after_lesson.get('lessons')}, 'predicates':len(rules.get('predicates',[])), 'result':result}
(ROOT/'scripts/evidence/LAYAG-sdk.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
