"""Measured Instant learning curves over existing corpora; no invented labels."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('D:/NeyviaRuns/laya-train')
ORIGIN = ROOT.parent / 'nx-c13-taste'
sys.path.insert(0, str(ROOT / 'src'))
os.environ['NEYVIA_TASTE_ASSETS'] = str(ORIGIN / '.agent_control/c13h-assets')
os.environ['NEYVIA_TASTE_DEPS'] = str(ORIGIN / '.agent_control/c13h-deps')
os.environ['NEYVIA_TASTE_STATE'] = str(DATA / 'vision')
os.environ['NEYVIA_TASTE_READ_CACHE'] = str(ORIGIN / 'proof/r11/learning/embeddings')
from grant_agent.laya_instant import Episodes, encode
from grant_agent.laya_instant_ingest import rows, ingest


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def curve(domain, training, heldout, calibration, run):
    local = Episodes(run / domain)
    labels = list({json.dumps(r['label']): r['label'] for r in training + heldout + calibration}.values())
    def learn(row, split):
        return local.learn(domain, row['input'], row['label'], row.get('source', 'frozen-corpus'),
                           split=split, evidence={'evaluationRole': split}, user=row.get('user', ''),
                           layer=row.get('layer', 'corrective'))
    for row in calibration:
        learn(row, 'calibration')
    report, learned = [], 0
    for target in (1, 3, 5, 10, 25):
        timings = []
        while learned < min(target, len(training)):
            timings.append(learn(training[learned], 'train')['labelToEffectMs'])
            learned += 1
        predictions = [local.query(domain, row['input'], labels=labels, user=row.get('user', '')) for row in heldout]
        novel = [(p, row) for p, row in zip(predictions, heldout) if p.get('confidenceKind') != 'explicit-exact-replay']
        recurrent = [(p, row) for p, row in zip(predictions, heldout) if p.get('confidenceKind') == 'explicit-exact-replay']
        admitted = [(p, row) for p, row in novel if not p['escalate']]
        repeats = [local.query(domain, row['input'], labels=labels, user=row.get('user', '')) for row in training[:learned]]
        report.append({'requestedLabels': target, 'availableLabels': learned,
            'calibrationCases': sum(len(index.samples) for index in local.calibration.values()),
            'externalCalibrationLabels': len(calibration),
            'heldoutCases': len(heldout), 'admitted': len(admitted),
            'novelCases': len(novel), 'recurrentCases': len(recurrent),
            'answerRate': len(admitted)/len(novel) if novel else None,
            'admittedAccuracy': sum(p['answer'] == r['label'] for p, r in admitted)/len(admitted) if admitted else None,
            'correctOfAllHeldout': sum(p['answer'] == r['label'] for p, r in zip(predictions, heldout)),
            'explicitReplayRate': sum(not p['escalate'] for p in repeats)/len(repeats) if repeats else None,
            'maxWriteMs': max(timings, default=None), 'maxWarmQueryMs': max((p['ms'] for p in repeats), default=None)})
    return report


def main():
    run = ROOT / '.agent_control/laya-train-runtime' / ('instant-curves-' + str(time.time_ns()))
    encode('warm encoder')
    manual = read(DATA / 'manual-curriculum.json')
    actual = read(DATA / 'manual-real-cases.json')
    adapt = lambda r: {'input': r['text'], 'label': r['label'], 'source': r.get('source', r.get('receipt', 'frozen-corpus'))}
    # Fixed labels and evaluation membership from the previous run are reused verbatim.
    receipt = read(DATA / 'receipt-curriculum.json')
    import hashlib
    split = lambda r: int(hashlib.sha256(r['group'].encode()).hexdigest()[:8], 16) % 5
    areas = {}
    areas['routing'] = curve('routing', list(map(adapt, manual))[:25], list(map(adapt, actual)), [], run)
    areas['outcomes'] = curve('outcomes', [adapt(r) for r in receipt if split(r)>1],
                              [adapt(r) for r in receipt if split(r)==0], [adapt(r) for r in receipt if split(r)==1], run)
    votes = [json.loads(line) for path in Path('D:/NeyviaRuns/laya-labels').glob('*.jsonl')
             for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    personal = [r for value in votes for r in rows(value) if r['domain'] == 'personal']
    areas['personal'] = curve('personal', personal[:-2], personal[-2:], [], run)
    # Components have representation/source notes but no independent preference labels.
    areas['components'] = [{'requestedLabels': n, 'availableLabels': 0, 'heldoutCases': 0,
                            'answerRate': None, 'admittedAccuracy': None, 'reason': 'No independent component labels'}
                           for n in (1, 3, 5, 10, 25)]
    layout = [r for r in read(DATA / 'vision/corrective-cases.json') if not r.get('excludedFromTraining')]
    pair = lambda r: {'input': {'screenshotPath': r['after'], 'screenshotPaths': [r['before'], r['after']]},
                      'label': r['preferred'], 'source': r['source']}
    areas['layout'] = curve('layout', [pair(r) for r in layout if r['split']=='train'][:25],
                            [pair(r) for r in layout if r['split']=='heldout'],
                            [pair(r) for r in layout if r['split']=='calibration'], run)
    from grant_agent.laya_selfcheck import instant
    from grant_agent import taste_vision
    layout_proof = []
    for row in layout:
        if row['split'] == 'heldout':
            result = taste_vision.compare(row['before'], row['after'], head_path=ROOT / 'tools/laya/capabilities/layout-head.json')
            layout_proof.append((1 if result.get('score', 0)>0 else -1) == row['preferred'])
    result = {'areas': areas, 'writeEffect': instant(), 'layoutRetainedHead': {'correct': sum(layout_proof), 'cases': len(layout_proof)},
              'boundary': 'Novel held-out cases exclude written examples. Exact replay is reported separately, never called held-out generalization. No augmentation or new human labels.'}
    (ROOT / 'scripts/evidence/LAYAT-instant-curves.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
