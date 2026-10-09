"""One image-layer model transcription per requested screenshot; retain failures."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.neyvia_perception import image_projection
from grant_agent.scene_core import transcribe,judge
RUN=ROOT/'.agent_control/layag-images'
RUN.mkdir(parents=True,exist_ok=True)
cases=[
    ('pdf-before',Path('D:/NeyviaRuns/tour/final-verified-theme/dark/pdf-full.png')),
    ('pdf-after',Path('D:/NeyviaRuns/ui-fix2/after-dark/pdf-full-dark-desktop.png')),
]
rows=[]
for name,path in cases:
    started=time.perf_counter()
    try:
        observation=image_projection(path,RUN,0)
        scene=transcribe('ui',observation)
        verdict=judge(scene)
        row={'name':name,'path':str(path),'verdict':verdict,'provenance':observation.get('provenance'),
             'totalMs':(time.perf_counter()-started)*1000}
        (RUN/(name+'.scene.json')).write_text(json.dumps(scene,indent=2),encoding='utf-8')
    except Exception as exc:
        row={'name':name,'path':str(path),'error':type(exc).__name__+': '+str(exc),'totalMs':(time.perf_counter()-started)*1000}
    rows.append(row)
    (ROOT/'scripts/evidence/LAYAG-images.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(row),flush=True)
