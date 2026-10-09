"""Evidence script: assemble the first draft of a brief and observe it once (no fixes)."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from grant_agent import laya_video as V
from grant_agent import scene_core

brief = V.read_brief(sys.argv[1])
out = Path(sys.argv[2])
lib = V.capture_index(brief['spec']['sources'])
V.assemble(brief, lib, out_dir=out)
started = time.perf_counter()
source = {'project': str(out)}
scene = scene_core.transcribe('video', source)
verdict = scene_core.judge(scene, record=False)
print(json.dumps({'seconds': round(time.perf_counter() - started, 1), 'renders': source['_renders'],
                  'findings': sorted({(f['predicate']) for f in verdict['findings']}), 'count': len(verdict['findings']),
                  'unknown': verdict['unknown'], 'admitted': verdict['admitted'],
                  'video': next(n for n in scene['nodes'] if n['id'] == 'video')['measurements']}, indent=1))
