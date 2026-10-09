"""Bounded explicit Luna labelling workers; root verifies every routing proposal."""
import concurrent.futures
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('D:/NeyviaRuns/laya-train/review')
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.autopilot_model import decide
from grant_agent import laya_curriculum as curriculum


def run():
    DATA.mkdir(parents=True, exist_ok=True)
    manual = json.loads((DATA.parent / 'manual-curriculum.json').read_text())
    procedures = '--procedures' in sys.argv
    prefix = 'procedures' if procedures else 'routing'
    actions = [r for r in manual if r.get('kind') == ('procedures' if procedures else 'actions')
               and (procedures or r.get('tool'))]
    schema = {'type': 'object', 'properties': {'rows': {'type': 'array', 'items': {
        'type': 'object', 'properties': {'id': {'type': 'string'}, 'request': {'type': 'string'}},
        'required': ['id', 'request'], 'additionalProperties': False}}},
        'required': ['rows'], 'additionalProperties': False}
    model = curriculum.load('manual-router')
    finished_all = {r['id'] for p in DATA.glob(prefix + '-[01].json')
                    for key in ('accepted', 'rejected') for r in json.loads(p.read_text()).get(key, [])}
    def routing(worker):
        saved = DATA / f'{prefix}-{worker}.json'
        previous = json.loads(saved.read_text()) if saved.exists() else {}
        accepted, rejected, receipts = [previous.get(k, []) for k in ('accepted', 'rejected', 'receipts')]
        selected = [r for r in actions if r['id'] not in finished_all][worker::2]
        for start in range(0, len(selected), 24):
            batch = selected[start:start+24]
            try:
                result = decide('Write one distinct natural user request per documented action. Preserve intent. '
                    'Do not include its tool ID or action identifier in the request. Do not fabricate capabilities. '
                    'Return the supplied id with each paraphrase. Actions: ' + json.dumps(batch), schema,
                    DATA, model='gpt-6-luna', reasoning_effort='low', timeout=240)
                receipts.append({k: v for k, v in result.items() if k != 'answer'})
                lookup = {r['id']: r for r in batch}
                for proposal in result['answer']['rows']:
                    original = lookup.get(proposal['id'])
                    if not original:
                        rejected.append({**proposal, 'reason': 'unknown-action'}); continue
                    ranked = curriculum.rank({**model, 'rows': [r for r in model['rows'] if r.get('kind') == ('procedures' if procedures else 'actions')]}, proposal['request'], 1)
                    resolved = ranked[0] if ranked else {}
                    row = {**proposal, 'label': original['label'], 'tool': original.get('tool'),
                           'family': original['id'], 'source': result['receiptPath'],
                           'resolvedAction': resolved.get('tool'), 'input': proposal['request']}
                    verified = resolved.get('id') == original['id'] if procedures else resolved.get('tool') == original['tool']
                    row['resolvedRecord'] = resolved.get('id')
                    (accepted if verified else rejected).append(row)
            except Exception as exc:
                receipts.append({'error': str(exc), 'receiptPath': getattr(exc, 'receipt_path', None)})
                break  # No silent provider substitution or repeated unavailable-route calls.
            saved.write_text(json.dumps({'accepted': accepted, 'rejected': rejected, 'receipts': receipts}, indent=2))
        saved.write_text(json.dumps({'accepted': accepted, 'rejected': rejected, 'receipts': receipts}, indent=2))
        return {'worker': worker, 'accepted': len(accepted), 'rejected': len(rejected), 'calls': len(receipts)}
    def visual(domain, index):
        cases = json.loads((DATA.parent / 'vision/corrective-cases.json').read_text())
        selected = [r for r in cases if r['split'] == 'train' and r['source'] == 'LAYAT-controlled-render-repair' and not r.get('excludedFromTraining')][index:index+2]
        visual_schema = {'type': 'object', 'properties': {'rows': {'type': 'array', 'items': {
            'type': 'object', 'properties': {'id': {'type': 'string'}, 'preferred': {'type': 'integer', 'enum': [-1, 0, 1]},
                                           'reason': {'type': 'string'}},
            'required': ['id', 'preferred', 'reason'], 'additionalProperties': False}}},
            'required': ['rows'], 'additionalProperties': False}
        answers, receipts = [], []
        for i, case in enumerate(selected):
            try:
                response = decide('Compare exactly these two images: FIRST is before; SECOND is after. Judge visible '
                    + domain + ' quality. Return exactly one row with id ' + str(i) + '; preferred 1 means second better, '
                    '-1 means first better, 0 uncertain/tied. Give a concrete visible reason. Do not infer Paul\'s taste.',
                    visual_schema, DATA, images=[Path(case['before']), Path(case['after'])],
                    model='gpt-6-luna', reasoning_effort='low', timeout=240)
                answers.extend(response['answer']['rows'])
                receipts.append({k: v for k, v in response.items() if k != 'answer'})
            except Exception as exc:
                receipts.append({'error': str(exc)})
        result = {'answer': {'rows': answers}, 'receipts': receipts,
                  'receiptPath': receipts[0].get('receiptPath', '') if receipts else ''}
        (DATA / (domain + '-labels.json')).write_text(json.dumps({'cases': selected, 'result': result}, indent=2))
        return {'worker': domain, 'completed': 'answer' in result}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(routing, i) for i in range(2)]
        if not procedures:
            futures += [pool.submit(visual, 'layout', 0), pool.submit(visual, 'components', 2)]
        for future in concurrent.futures.as_completed(futures):
            print(json.dumps(future.result()), flush=True)


if __name__ == '__main__':
    run()
