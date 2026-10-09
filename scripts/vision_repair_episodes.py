"""Write any cached model look that has no episode yet (a run killed between caching a look and
writing it). remember() is idempotent per look receipt, so this only fills real gaps.

Usage: python scripts/vision_repair_episodes.py D:/NeyviaRuns/VISION/render-1 [...]
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def main():
    from grant_agent.laya_vision import remember
    for run in map(Path, sys.argv[1:]):
        domain = 'ui-look' if 'stream' in run.name else 'render-look'
        written = 0
        for path in sorted((run / 'looks').glob('*.json')):
            result = json.loads(path.read_text(encoding='utf-8'))
            if domain == 'ui-look':
                from laya_glance_eval import _scene
                from grant_agent.laya_glance import transcribe
                scene = transcribe(_scene(result['image']))
            else:
                scene = {'nodes': []}
            out = remember(run, result['image'], scene, result, domain=domain, lessons=domain == 'ui-look')
            written += bool(out['look'].get('learned'))
        print(run.name, 'looks', len(list((run / 'looks').glob('*.json'))), 'newly written', written)


if __name__ == '__main__':
    main()
