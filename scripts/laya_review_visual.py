"""Separate human preferences, auxiliary Luna labels and unchanged pixel gate."""
import json
from pathlib import Path
import time
from laya_instant_session import ROOT, DATA, ORIGIN, read, curve, rows, ingest
from grant_agent import taste_vision
from grant_agent.laya_instant import Episodes, input_key


def main():
    run = ROOT / '.agent_control/laya-train-runtime' / ('visual-review-' + str(time.time_ns()))
    paths = sorted((ORIGIN/'proof/votes-export').rglob('*.json')) + [ORIGIN/'proof/r10/paul-votes.json'] + sorted(Path('D:/NeyviaRuns/laya-labels').glob('*.jsonl'))
    personal = []
    for path in paths:
        if not path.is_file():
            continue
        raw = path.read_text(encoding='utf-8-sig')
        values = [json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix == '.jsonl' else [json.loads(raw)]
        personal.extend({**r, 'source': str(path)} for value in values for r in rows(value) if r['domain'] == 'personal')
    personal = list({input_key(r['input']): r for r in personal}.values())
    # Both inboxes export round 12. Keep each pair once and keep the entire
    # round out of the curve's training side, even when its encoding differs.
    r12, earlier = {}, []
    for row in personal:
        value = row['input']
        if str(value.get('pageId', '')).startswith('r12/'):
            r12[value['pageId'].split('/', 1)[1]] = row
        elif Path(row['source']).name == 'paul-r12.jsonl':
            r12.setdefault(value['comparison'], row)
        else:
            earlier.append(row)
    result = {'personal': curve('personal', earlier, list(r12.values()), [], run)}
    result['personalBoundary'] = {'uniqueComparativeLabels': len(earlier)+len(r12), 'heldout': 'entire round 12, pair-deduplicated across exports; author identity and guidance excluded', 'sourceFiles': [str(p) for p in paths if p.is_file()]}
    layout = [r for r in read(DATA/'vision/corrective-cases.json') if not r.get('excludedFromTraining')]
    adapt = lambda r: {'input': {'screenshotPath': r['after'], 'screenshotPaths': [r['before'], r['after']]},
                       'label': r['preferred'], 'source': r['source']}
    result['layout'] = curve('layout', [adapt(r) for r in layout if r['split']=='train'][:25],
        [adapt(r) for r in layout if r['split']=='heldout'], [], run)
    observed = [taste_vision.compare(r['before'], r['after'], head_path=ROOT/'tools/laya/capabilities/layout-head.json')
                for r in layout if r['split']=='heldout']
    result['retainedLayoutHead'] = {'cases': len(observed), 'correct': sum((1 if p.get('score', 0)>0 else -1)==r['preferred']
        for p, r in zip(observed, [r for r in layout if r['split']=='heldout']))}
    result['auxiliary'] = {}
    local = Episodes(DATA/'review/learned-runtime')
    for domain in ('components', 'layout'):
        value = read(DATA/'review'/f'{domain}-labels.json')
        accepted, rejected = [], []
        for label in value.get('result', {}).get('answer', {}).get('rows', []):
            if label['id'] not in [str(i) for i in range(len(value['cases']))]:
                rejected.append({**label, 'reason': 'invalid-case-id'}); continue
            case = value['cases'][int(label['id'])]
            if label['preferred'] == case['preferred']:
                source = value['result']['receipts'][int(label['id'])]['receiptPath'] + '#' + label['id']
                legacy_source = value['result']['receiptPath'] + '#' + label['id']
                if legacy_source != source:
                    local.forget(legacy_source)
                accepted.append(local.learn(domain, adapt(case)['input'], label['preferred'],
                    source, weight=.5,
                    evidence={'model': 'gpt-6-luna', 'reason': label['reason'], 'correctiveCase': case.get('id'),
                              'notHumanTaste': True}))
            else:
                rejected.append(label)
        result['auxiliary'][domain] = {'accepted': len(accepted), 'rejected': len(rejected),
                                      'heldoutCases': 0, 'accuracy': None, 'boundary': 'weak critic labels checked against corrective labels, not independent human preference proof'}
    result['ingestion'] = ingest(ROOT/'.agent_control/laya-train-runtime/instant-admitted')
    (ROOT/'scripts/evidence/LAYAT-review-visual.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
