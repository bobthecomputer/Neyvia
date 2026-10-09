"""Two owned Neyvia surfaces through Obscura; no desktop windows, no tour."""
import json
import os
from pathlib import Path
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'scripts'))
import placement_shots as shots
from grant_agent.scene_core import transcribe,judge
RUN=ROOT/'.agent_control/layag-live'
RUN.mkdir(parents=True,exist_ok=True)
shots.BACKEND,shots.ENGINE=49091,49092
shots.SCRATCH=RUN/'runtime'
shots.SMALL_STATE=RUN/'state'
shots.OUT=RUN/'screenshots'
shots.OUT.mkdir(parents=True,exist_ok=True)
shots.BUILD=Path('D:/NeyviaRuns/ui-fix2/build-before')
shots.EXE=Path('C:/Users/user/Projects/nx-c13-taste/scripts/evidence/c13-runtime/obscura-v0.2.4/obscura.exe')
shots.PDF=Path('D:/NeyviaRuns/tour/final-verified-theme/state/final-verified-theme-dark/home/tour-fixtures/INTN.pdf')
report={'errors':[],'observations':[],'boundary':'Current worktree backend with recorded before UI bundle; owned Obscura, ports 49091/49092'}
rig=shots.Rig(report)
try:
    rig.start()
    rig.session(shots.DESKTOP)
    observer=(ROOT/'src/grant_agent/perception_scene.js').read_text(encoding='utf-8')
    for name in ('home','pdf'):
        if name=='pdf':
            target=shots.SMALL_STATE/'sample.pdf'
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(shots.PDF,target)
            lines='G opened: pdf.state()["requested"]["source"] == '+json.dumps(str(target))+'\nrun pdf.open-and-read(source="sample.pdf", page=1, phrase="INTN")'
            receipt=rig.js("""lines => { globalThis.__layagPdfOpen=null; fetch('/api/ui/tools/call',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool:'neyvia.cl',arguments:{lines}})}).then(r=>r.json()).then(r=>{globalThis.__layagPdfOpen=r;}).catch(e=>{globalThis.__layagPdfOpen={error:String(e)};}); return {requested:true}; }""",lines)
            report['pdfOpen']=receipt
            rig.wait("() => !!document.querySelector('.nx-pdf-page, .nx-pdf-empty')",40)
            report['pdfOpen']=rig.js("() => globalThis.__layagPdfOpen")
        before=time.perf_counter()
        raw=rig.page.evaluate(observer,{})
        scene=transcribe('ui',raw)
        verdict=judge(scene)
        elapsed=(time.perf_counter()-before)*1000
        shot=shots.OUT/(name+'.png')
        rig.page.screenshot(path=str(shot))
        (RUN/(name+'.scene.json')).write_text(json.dumps(scene,indent=2),encoding='utf-8')
        report['observations'].append({'surface':name,'verdict':verdict,'transcribeAndJudgeMs':elapsed,'screenshot':str(shot)})
except Exception as exc:
    report['errors'].append(type(exc).__name__+': '+str(exc))
    try:report['pdfOpen']=rig.js('() => globalThis.__layagPdfOpen')
    except Exception:pass
finally:
    rig.stop()
    (ROOT/'scripts/evidence/LAYAG-live.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
print(json.dumps({'surfaces':len(report['observations']),'errors':report['errors']}))
