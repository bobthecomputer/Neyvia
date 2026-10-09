"""Provenance-first C7, integration receipt and manual episode collection."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('D:/NeyviaRuns/laya-train/review')
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.laya_curriculum import receipt_text, outcome_input


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def walk(value, pointer=''):
    if isinstance(value, dict):
        yield pointer, value
        for key, item in value.items():
            if not any(word in key.lower() for word in ('password', 'credential', 'secret', 'token', 'cookie')):
                yield from walk(item, pointer + '/' + key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from walk(item, pointer + '/' + str(i))


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    c7 = ROOT.parent / 'nx-c7-edge'
    inventory, contracts, outcomes, routing = [], [], [], []
    for family in read(c7 / 'scripts/evidence/C7.json')['families']:
        path = c7 / family['receipt']['path']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != family['receipt']['sha256']:
            raise ValueError('C7 receipt hash mismatch: ' + str(path))
        rows = json.loads(raw)['rows']
        inventory.append({'family': family['family'], 'cases': len(rows), 'sha256': family['receipt']['sha256']})
        for row in rows:
            if row['status'] not in ('passed', 'failed'):
                continue
            # Contract status is the label, never an input, never tool success.
            contracts.append({'domain': 'contract:' + family['family'],
                'input': {'contracts': row.get('contracts', []), 'category': row.get('category'),
                          'observation': receipt_text(row.get('detail', {}))},
                'label': row['status'] == 'passed', 'family': family['family'],
                'source': str(path), 'evidence': {'caseId': row['id'], 'sha256': family['receipt']['sha256'],
                    'labelMeaning': 'contract-satisfied-including-expected-refusal'}})
    files, errors, seen = 0, [], set()
    folder = ROOT.parent / 'nx-int-final/scripts/evidence'
    for path in sorted(folder.rglob('*.json')):
        if path.stat().st_size > 50_000_000:
            errors.append({'path': str(path), 'reason': 'bounded-reader-50MB'}); continue
        try:
            value = read(path)
        except (ValueError, OSError) as exc:
            errors.append({'path': str(path), 'reason': type(exc).__name__}); continue
        files += 1
        for pointer, item in walk(value):
            tool = item.get('toolId') or item.get('tool') or item.get('name')
            if not isinstance(tool, str) or '.' not in tool or not isinstance(item.get('ok'), bool):
                continue
            if not isinstance(item.get('result'), dict):
                continue
            observation = outcome_input(item)
            # Envelope ok is independent of the projected result body. Explicit
            # status/error inside the result is legitimate post-step evidence.
            key = (tool, observation, item['ok'])
            if key in seen:
                continue
            seen.add(key)
            outcomes.append({'domain': 'outcomes', 'input': observation, 'label': 'success' if item['ok'] else 'failure',
                'family': tool.split('.')[0], 'tool': tool, 'source': str(path),
                'evidence': {'pointer': pointer, 'labelMeaning': 'observed-tool-envelope-ok'}})
    for row in read(DATA.parent / 'manual-curriculum.json'):
        routing.append({'domain': 'routing', 'input': row['text'], 'label': row['label'],
            'family': row['id'], 'source': row['source'], 'evidence': {'manualRecord': row['id'], 'kind': row['kind']}})
    report = {'c7Cases': len(contracts), 'c7Families': inventory, 'c7Labels': dict(Counter(str(r['label']) for r in contracts)),
              'receiptFilesRead': files, 'outcomes': len(outcomes), 'outcomeLabels': dict(Counter(r['label'] for r in outcomes)),
              'routing': len(routing), 'errors': errors,
              'boundary': 'C7 contract pass is not tool success. Only explicit tool envelope booleans label post-step outcomes.'}
    for name, value in [('contracts', contracts), ('outcomes', outcomes), ('routing', routing), ('inventory', report)]:
        (DATA / (name + '.json')).write_text(json.dumps(value, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'c7Families'}), flush=True)


if __name__ == '__main__':
    main()
