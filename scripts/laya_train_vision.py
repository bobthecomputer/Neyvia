"""Refit and measure the existing frozen-pixel head in task-local D: state."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import sys
import time
import argparse
import faulthandler
os.environ['OPENBLAS_NUM_THREADS'] = '2'
os.environ['OMP_NUM_THREADS'] = '2'

REPO = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train')
ORIGIN = Path('C:/Users/user/Projects/nx-c13-taste')
sys.path.insert(0, str(REPO / 'src'))
os.environ['NEYVIA_TASTE_ASSETS'] = str(ORIGIN / '.agent_control/c13h-assets')
os.environ['NEYVIA_TASTE_DEPS'] = str(ORIGIN / '.agent_control/c13h-deps')
os.environ['NEYVIA_TASTE_STATE'] = str(RUN / 'vision')
os.environ['NEYVIA_TASTE_READ_CACHE'] = str(REPO / 'proof/r11/learning/embeddings')
from grant_agent import taste_vision as vision


def main(resume=False):
    faulthandler.dump_traceback_later(60, repeat=True)
    vision.STATE.mkdir(parents=True, exist_ok=True)
    for name in ([] if resume else ('corrective-cases.json', 'corrective-head.json', 'personal-cases.json')):
        shutil.copyfile(ORIGIN / 'proof/r11/learning' / name, vision.STATE / name)
    # Existing immutable embedding cache is copied, not regenerated or changed in the source task.
    cache = REPO / 'proof/r11/learning/embeddings'
    if not resume:
        shutil.copytree(cache, vision.STATE / 'embeddings', dirs_exist_ok=True)
    report = {'started': time.time(), 'scope': 'Existing real/historical and synthetic rendered cases; no claim of general web-layout accuracy'}
    for layer in ('corrective', 'personal'):
        print('fitting', layer, flush=True)
        fitted = vision.train(layer)
        predictions = []
        for row in vision.cases(layer):
            if row['split'] != 'heldout':
                continue
            result = vision.compare(row['before'], row['after'], layer)
            predicted = 1 if result.get('score', 0) > 0 else -1
            predictions.append({'id': row['id'], 'group': row['group'], 'source': row['source'],
                                'correct': predicted == row['preferred'], 'answerCorrect':
                                    (result.get('answer') == ('after' if row['preferred'] == 1 else 'before')) if not result['escalate'] else None,
                                'result': result})
        answered = [p for p in predictions if not p['result']['escalate']]
        report[layer] = {k: v for k, v in fitted.items() if k not in ('weights', 'heldoutCaseIds')}
        report[layer].update(answerRate=len(answered)/len(predictions) if predictions else 0,
            answeredAccuracy=sum(p['answerCorrect'] for p in answered)/len(answered) if answered else None,
            predictions=predictions)
        vision.save(RUN / 'vision-metrics.json', report)
        print(layer, json.dumps({k: v for k, v in report[layer].items() if k != 'predictions'}), flush=True)
    report['finished'] = time.time()
    # Retain the small admitted head with the callable capability, not just a report.
    shutil.copyfile(vision.STATE / 'corrective-head.json', REPO / 'tools/laya/capabilities/layout-head.json')
    vision.save(RUN / 'vision-metrics.json', report)
    vision.save(REPO / 'scripts/evidence/LAYAT-vision-metrics.json', {k: ({a: b for a, b in v.items() if a != 'predictions'} if isinstance(v, dict) else v) for k, v in report.items()})
    faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    main(parser.parse_args().resume)
