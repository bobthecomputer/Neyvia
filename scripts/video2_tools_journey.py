"""Evidence script (track VIDEO2): an agent's journey through the neyvia.video.* tools on the one video stack.

    PYTHONPATH=src python scripts/video2_tools_journey.py [--out D:/NeyviaRuns/video/track-video/v3work/edl-runs/journey]

new -> add two real captures -> keyframe pushes -> caption -> split -> crossfade -> timeline (video-edit judge)
-> render (HyperFrames headless) -> judge + transcribe + contracts (the one video judge) -> contact sheet
-> Studio start/stop on 49165 (--no-open) -> a synthetic A/B vote into a scratch episode root (never Paul's).
Writes scripts/evidence/VIDEO2-tools-journey.json. Nothing opens a window.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
import os  # noqa: E402

os.environ.setdefault('NEYVIA_VIDEO_RUNS', 'D:/NeyviaRuns/video/track-video/v3work/edl-runs')
from grant_agent.neyvia_video import call  # noqa: E402

DARK = Path('D:/NeyviaRuns/video/track-video/recapture/dark')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=os.environ['NEYVIA_VIDEO_RUNS'] + '/journey')
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    project = out / 'project'
    steps = []

    def step(name, a, check):
        started = time.perf_counter()
        try:
            result = call(None, name, a)
            ok, note = check(result)
        except Exception as exc:  # a failing step is recorded, not hidden
            result, ok, note = None, False, type(exc).__name__ + ': ' + str(exc)[:300]
        steps.append({'tool': 'neyvia.' + name, 'ok': bool(ok), 'note': note, 'seconds': round(time.perf_counter() - started, 2)})
        print(steps[-1], flush=True)
        return result

    p = str(project)
    step('video.new', {'project': p, 'width': 1280, 'height': 720, 'fps': 30, 'title': 'Journey'},
         lambda r: (r['ok'] and (project / 'index.html').is_file(), 'index.html compiled'))
    step('video.add', {'project': p, 'kind': 'image', 'src': str(DARK / 'agent-view-full.png'), 'start': 0, 'duration': 3, 'id': 'shot-1'},
         lambda r: (r['clips'] == 1, f"{r['clips']} clip, {r['duration']} s"))
    step('video.add', {'project': p, 'kind': 'image', 'src': str(DARK / 'laya-full.png'), 'start': 3, 'duration': 3, 'id': 'shot-2'},
         lambda r: (r['clips'] == 2 and r['duration'] == 6, f"{r['clips']} clips, {r['duration']} s"))
    for sid in ('shot-1', 'shot-2'):
        step('video.keyframe', {'project': p, 'id': sid, 'property': 'scale', 'at': 0, 'value': 1.0, 'ease': 'none'}, lambda r: (True, 'scale 1.0 at 0'))
        step('video.keyframe', {'project': p, 'id': sid, 'property': 'scale', 'at': 3, 'value': 1.06, 'ease': 'none'}, lambda r: (True, 'scale 1.06 at 3'))
    step('video.caption', {'project': p, 'text': 'Then checks its work.', 'start': 3.3, 'duration': 2.4, 'id': 'cap-1'},
         lambda r: (r['clips'] == 3, f"caption added ({r['clips']} clips)"))
    step('video.split', {'project': p, 'id': 'shot-1', 'at': 1.5},
         lambda r: (r['clip']['id'] == 'shot-1-b' and r['clips'] == 4, 'second half ' + r['clip']['id']))
    step('video.transition', {'project': p, 'id': 'shot-2', 'kind': 'crossfade', 'seconds': 0.4},
         lambda r: (r['clip']['transitionIn']['kind'] == 'crossfade', 'crossfade in'))
    tl = step('video.timeline', {'project': p},
              lambda r: (any(n['kind'] == 'timeline-clip' for n in r['scene']['nodes']),
                         f"{sum(n['kind'].startswith('clip-') for n in r['scene']['nodes'])} EDL clips, "
                         f"{sum(n['kind'] == 'timeline-clip' for n in r['scene']['nodes'])} HyperFrames rows, "
                         f"{len(r['verdict']['findings'])} pre-render findings {sorted({f['predicate'] for f in r['verdict']['findings']})}"))
    render = step('video.render', {'project': p, 'quality': 'draft', 'workers': 2},
                  lambda r: (r['ok'], f"{r['seconds']} s -> {Path(r['output']).name}"))
    video = render['output'] if render and render.get('ok') else str(project / 'renders/out.mp4')
    judged = step('video.judge', {'video': video, 'project': p},
                  lambda r: (True, f"{len(r['verdict']['findings'])} findings {sorted({f['predicate'] for f in r['verdict']['findings']})}, unknown {r['verdict']['unknown']}"))
    scene = step('video.transcribe', {'video': video, 'project': p},
                 lambda r: (r['domain'] == 'video' and any(n['kind'] == 'caption' for n in r['nodes']),
                            f"{len(r['nodes'])} nodes: " + ', '.join(sorted({n['kind'] for n in r['nodes']}))))
    step('video.contracts', {'video': video, 'project': p},
         lambda r: (r['passed'], ', '.join(f"{k} {'pass' if v['passed'] else 'FAIL'}" for k, v in r['contracts'].items())))
    step('video.contact_sheet', {'video': video, 'out': str(out / 'sheet.png'), 'count': 12},
         lambda r: (Path(r['sheet']).is_file(), r['sheet']))
    st = step('video.studio', {'project': p, 'port': 49165},
              lambda r: (r['ok'], f"Studio answered on {r.get('url')} ({r.get('bytes')} bytes)"))
    step('video.studio', {'project': p, 'port': 49165, 'stop': True}, lambda r: (r['ok'] and r.get('stopped'), 'stopped pid ' + str(r.get('pid'))))
    if scene:
        votes = out / 'vote-scratch'
        os.environ['NEYVIA_VIDEO_JOURNEY_ROOT'] = str(votes)
        from grant_agent.laya_video import vote
        started = time.perf_counter()
        try:
            rows = vote(str(votes), scene, scene, 'a', user='video2-journey-synthetic', reason='mechanism check only', source='journey')
            steps.append({'tool': 'laya_video.vote (what neyvia.video.vote calls)', 'ok': len(rows) == 2, 'note': '2 personal episodes in a scratch root, synthetic user',
                          'seconds': round(time.perf_counter() - started, 2)})
        except Exception as exc:
            steps.append({'tool': 'laya_video.vote', 'ok': False, 'note': type(exc).__name__ + ': ' + str(exc)[:200], 'seconds': 0})
    result = {'passed': all(s['ok'] for s in steps), 'steps': steps, 'project': p, 'video': video,
              'judge': {'findings': [{'predicate': f['predicate'], 'node': f['node']} for f in (judged or {}).get('verdict', {}).get('findings', [])]},
              'note': 'Every judgement goes through laya_video (domain video); timeline through laya_video_edit (domain video-edit).'}
    (REPO / 'scripts/evidence/VIDEO2-tools-journey.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'failed': [s for s in steps if not s['ok']]}, indent=1))


if __name__ == '__main__':
    main()
