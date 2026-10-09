"""Frozen family-separated review curves; never tune on these outcomes."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('D:/NeyviaRuns/laya-train/review')
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.laya_instant import Episodes, encode, input_key


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def bucket(family):
    return int(hashlib.sha256(family.encode()).hexdigest()[:8], 16) % 5


def curve(domain, training, heldout, run):
    # Membership and order are functions of provenance, not observed accuracy.
    groups = defaultdict(list)
    held_keys = {input_key(r['input']) for r in heldout}
    representatives = {}
    for row in training:
        if input_key(row['input']) not in held_keys:
            # A manual declaration and its paraphrases are one labelled family,
            # not multiple independent calibration observations. Prefer the
            # verified natural request when that family has one.
            key = (row.get('region', row['family']), row['family']) if domain.startswith('routing') else (row.get('region', row['family']), input_key(row['input']))
            old = representatives.get(key)
            if old is None or ('request' in row and 'request' not in old):
                representatives[key] = row
    for row in representatives.values():
        groups[row.get('region', row['family'])].append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: hashlib.sha256(json.dumps(r['input'], sort_keys=True).encode()).hexdigest())
    local = Episodes(run / domain)
    labels = list({json.dumps(r['label']): r['label'] for r in training + heldout}.values())
    learned, result = set(), []
    for n in (1, 3, 5, 10, 25):
        timings = []
        for region, rows in groups.items():
            for row in rows[:n]:
                key = (input_key(row['input']), row['source'])
                if key in learned:
                    continue
                effect = local.learn(domain, row['input'], row['label'], row['source'], split='train',
                    evidence={**row.get('evidence', {}), 'family': row['family'], 'region': region})
                timings.append(effect.get('labelToEffectMs', 0)); learned.add(key)
        predictions = [local.query(domain, row['input'], labels=labels) for row in heldout]
        admitted = [(p, r) for p, r in zip(predictions, heldout) if not p['escalate'] and p.get('confidenceKind') != 'explicit-exact-replay']
        result.append({'labelsPerRegion': n, 'regions': len(groups), 'episodes': len(learned),
            'heldoutCases': len(heldout), 'heldoutFamilies': len({r['family'] for r in heldout}),
            'admitted': len(admitted), 'correct': sum(p['answer'] == r['label'] for p, r in admitted),
            'answerRate': len(admitted)/len(heldout) if heldout else None,
            'admittedAccuracy': sum(p['answer'] == r['label'] for p, r in admitted)/len(admitted) if admitted else None,
            'calibrationCases': max((len(v.samples) for v in local.calibration.values()), default=0),
            'writeP50Ms': sorted(timings)[len(timings)//2] if timings else None,
            'writeMaxMs': max(timings, default=None),
            'queryP95Ms': sorted(p['ms'] for p in predictions)[int(.95*(len(predictions)-1))] if predictions else None,
            'predictions': [{'answer': p['answer'], 'expected': r['label'], 'family': r['family'],
                             'reason': p.get('reason'), 'admitted': not p['escalate']} for p, r in zip(predictions, heldout)]})
        print(json.dumps({'domain': domain, **{k: v for k, v in result[-1].items() if k != 'predictions'}}), flush=True)
        (DATA / (domain + '-curve-progress.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main():
    encode('warm frozen encoder')
    run = ROOT / '.agent_control/laya-train-runtime' / ('review-' + str(time.time_ns()))
    manual = read(DATA / 'routing.json')
    augmented = list({r['id']: r for pattern in ('routing-[01].json', 'procedures-[01].json')
                      for p in sorted(DATA.glob(pattern)) for r in read(p)['accepted']}.values())
    # All variants of a held-out action stay out of training, including manuals.
    # Fold zero was used to diagnose the old encoder. Freeze untouched fold four
    # for this final method; retain the old failed probe as evidence.
    held = [r for r in augmented if bucket(r['family']) == 4]
    training = [r for r in manual + augmented if bucket(r['family']) != 4]
    for row in training:
        row['region'] = row['label']
    frozen = [{'input': r['text'], 'label': r['label'], 'family': r['receipt'], 'source': r['receipt']}
              for r in read(DATA.parent / 'manual-real-cases.json')]
    frozen = list({input_key(r['input']): r for r in frozen}.values())
    outcomes = read(DATA / 'outcomes.json')
    outcome_train = [r for r in outcomes if bucket(r['family']) != 0]
    outcome_held = [r for r in outcomes if bucket(r['family']) == 0]
    result = {'method': 'leave-one-out cross-conformal; 0.95 nominal level; selective accuracy measured independently',
        'boundary': 'Labels capped per training region; calibration pooled within domain. Action families disjoint for augmentation. Real prompts deduplicated. Outcomes split by tool namespace. Heldout never written.',
        'areas': {}}
    for domain, train, evaluation in [('routing', training, held), ('routing-real', training, frozen),
                                      ('outcomes', outcome_train, outcome_held)]:
        result['areas'][domain] = curve(domain, train, evaluation, run)
        (DATA / 'curves.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (ROOT / 'scripts/evidence/LAYAT-review-curves.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
